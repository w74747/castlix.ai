"""
cost_tracker.py — تتبع تكلفة حقيقي متصل بقاعدة بيانات PostgreSQL والملف المحلي.

يسجّل استهلاك كل مرحلة (Tavily, Perplexity, LlamaParse, Gamma, LLM) تلقائياً،
ويحفظ النتائج في جدول cost_logs في PostgreSQL بالإضافة للملف الاحتياطي costs.jsonl.
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List

import config
from database import CostLog, SessionLocal
from utils.telegram_text import esc

logger = logging.getLogger("CastlixCost")


@dataclass
class CostTracker:
    service_type: str
    user_id: int
    tavily_calls: int = 0
    tavily_credits: float = 0.0
    perplexity_calls: int = 0
    llama_pages: int = 0
    gamma_credits: float = 0.0
    llm_in: int = 0
    llm_out: int = 0
    stages: Dict[str, str] = field(default_factory=dict)   # اسم المرحلة -> ok | failed: سبب | skipped: سبب
    started: float = field(default_factory=time.time)

    # ---- تسجيل الاستهلاك ----
    def add_tavily(self, credits: float = 1.0) -> None:
        self.tavily_calls += 1
        self.tavily_credits += credits

    def add_perplexity(self, calls: int = 1) -> None:
        self.perplexity_calls += calls

    def add_llama_pages(self, pages: int) -> None:
        self.llama_pages += max(0, int(pages))

    def add_gamma_credits(self, credits: float) -> None:
        self.gamma_credits += float(credits or 0)

    def add_llm(self, tokens_in: int, tokens_out: int = 0) -> None:
        self.llm_in += int(tokens_in)
        self.llm_out += int(tokens_out)

    def add_tokens(self, total_tokens: int) -> None:
        # تسجيل إجمالي التوكنز في حال لم يحدد المزود المدخلات والمخرجات منفصلين
        self.llm_in += int(total_tokens)

    def stage(self, name: str, status: str) -> None:
        self.stages[name] = status

    # ---- حساب التكلفة ----
    def breakdown_usd(self) -> Dict[str, float]:
        p = config.PRICES
        return {
            "tavily": self.tavily_credits * p.get("tavily_usd_per_credit", 0.008),
            "perplexity": self.perplexity_calls * p.get("perplexity_usd_per_call", 0.005),
            "llamaparse": self.llama_pages * p.get("llama_usd_per_page", 0.003),
            "gamma": self.gamma_credits * p.get("gamma_usd_per_credit", 0.0),
            "llm": (
                self.llm_in / 1e6 * p.get("llm_usd_per_mtok_in", 3.0) +
                self.llm_out / 1e6 * p.get("llm_usd_per_mtok_out", 15.0)
            ),
        }

    def total_usd(self) -> float:
        return round(sum(self.breakdown_usd().values()), 4)

    # ---- إعداد تقرير HTML للمدير ----
    def report_html(self) -> str:
        total = self.total_usd()
        omr = round(total * config.USD_TO_OMR, 4)
        failed = [f"{k}: {v}" for k, v in self.stages.items() if not v.startswith("ok")]
        gamma_note = "" if config.PRICES.get("gamma_usd_per_credit") else " (سعر الكريدت غير مضبوط)"
        lines: List[str] = [
            "🔔 <b>تقرير استهلاك وتكلفة العملية</b>",
            "━━━━━━━━━━━━━━━",
            f"• المستخدم: <code>{self.user_id}</code>",
            f"• الخدمة: <code>{esc(self.service_type)}</code>",
            f"• المدة: {time.time() - self.started:.0f} ثانية",
            "",
            f"• Tavily: {self.tavily_calls} طلب / {self.tavily_credits:g} كريدت",
            f"• Perplexity: {self.perplexity_calls} طلب",
            f"• LlamaParse: {self.llama_pages} صفحة",
            f"• Gamma: {self.gamma_credits:g} كريدت{gamma_note}",
            f"• LLM Tokens: {self.llm_in + self.llm_out:,} توكن",
            "━━━━━━━━━━━━━━━",
            f"💰 <b>إجمالي التكلفة: ${total} (~{omr} OMR)</b>",
        ]
        if failed:
            lines += ["", "⚠️ <b>مراحل واجهت مشاكل:</b>"] + [f"• {esc(f)}" for f in failed]
        return "\n".join(lines)

    # ---- الحفظ الدائم (DB + File) ----
    def persist(self) -> None:
        """حفظ التكلفة في جدول PostgreSQL وملف JSONL الاحتياطي."""
        total = self.total_usd()

        # 1. الحفظ في PostgreSQL
        if SessionLocal:
            db = None
            try:
                db = SessionLocal()
                log_entry = CostLog(
                    track=self.service_type,
                    user_id=self.user_id,
                    tavily_credits=int(self.tavily_credits),
                    llama_pages=self.llama_pages,
                    gamma_credits=int(self.gamma_credits),
                    llm_tokens=self.llm_in + self.llm_out,
                    total_cost_usd=total,
                    stages=self.stages
                )
                db.add(log_entry)
                db.commit()
                logger.info("تم حفظ سجل التكلفة في جدول cost_logs بـ PostgreSQL بنجاح.")
            except Exception as exc:
                logger.error(f"فشل حفظ سجل التكلفة في قاعدة البيانات: {exc}")
                if db:
                    db.rollback()
            finally:
                if db:
                    db.close()

        # 2. الحفظ في الملف المحلي كنسخة احتياطية
        try:
            os.makedirs(os.path.dirname(config.COST_LOG_PATH) or ".", exist_ok=True)
            rec = {
                "ts": int(time.time()),
                "user_id": self.user_id,
                "service": self.service_type,
                "tavily_calls": self.tavily_calls,
                "tavily_credits": self.tavily_credits,
                "perplexity_calls": self.perplexity_calls,
                "llama_pages": self.llama_pages,
                "gamma_credits": self.gamma_credits,
                "llm_in": self.llm_in,
                "llm_out": self.llm_out,
                "usd_est": total,
                "stages": self.stages,
            }
            with open(config.COST_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning(f"تعذر كتابة سجل التكلفة في الملف المحلي: {exc}")
