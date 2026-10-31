"""
presentation.py — وكيل العرض التقديمي عبر Gamma API v1.0 (مصحّح).

ما كان خاطئاً: المسار والترويسة والحقول كانت قديمة/غير صحيحة، والكود كان ينتظر الرابط في الرد الأول
بينما التوليد غير متزامن. الصحيح: POST إلى public-api.gamma.app/v1.0/generations مع X-API-KEY
ثم استعلام GET /generations/{id} كل ~5 ثوانٍ حتى status=completed (أو failed).
الوصول للـAPI يتطلب خطة Gamma مدفوعة. الأرقام في العرض تأتي من النموذج المالي فقط.
"""
import logging
import time
from typing import Any, Dict, Optional

import requests

import config

logger = logging.getLogger("CastlixPresentationAgent")
BASE = "https://public-api.gamma.app/v1.0"


class PresentationAgent:
    def __init__(self) -> None:
        if not config.GAMMA_API_KEY:
            raise ValueError("GAMMA_API_KEY غير مضبوط")
        self.headers = {
            "X-API-KEY": config.GAMMA_API_KEY,
            "Content-Type": "application/json",
            "accept": "application/json"
        }

    @staticmethod
    def _fmt_money(v: Optional[float]) -> str:
        return "غير متاح" if v is None else f"{v:,.0f} دولار"

    @staticmethod
    def _fmt_pct(v: Optional[float]) -> str:
        return "غير متاح" if v is None else f"{v:.1%}"

    def _figures_block(self, m: Dict[str, Any], undocumented: int, total: int) -> str:
        payback = "أكثر من 5 سنوات" if m.get("payback") is None else f"{m['payback']:.1f} سنة"
        dscr = "غير متاح" if m.get("min_dscr") is None else f"{m['min_dscr']:.2f}x"
        return (
            f"- رأس المال: {self._fmt_money(m.get('capex'))}\n"
            f"- إيراد السنة 1: {self._fmt_money(m.get('revenue_y1'))} | إيراد السنة 5: {self._fmt_money(m.get('revenue_y5'))}\n"
            f"- EBITDA السنة 5: {self._fmt_money(m.get('ebitda_y5'))} | هامش EBITDA السنة 3: {self._fmt_pct(m.get('ebitda_margin_y3'))}\n"
            f"- NPV بدون قيمة نهائية: {self._fmt_money(m.get('npv_explicit'))} | شاملاً القيمة النهائية: {self._fmt_money(m.get('npv_tv'))}\n"
            f"- IRR المشروع (شاملاً القيمة النهائية): {self._fmt_pct(m.get('irr_tv'))} | IRR حملة الأسهم: {self._fmt_pct(m.get('irr_equity'))}\n"
            f"- فترة الاسترداد: {payback} | أدنى DSCR: {dscr}\n"
            f"- حالة التوثيق: {undocumented} من {total} فرضية غير موثقة"
        )

    def generate_pitch_deck(
        self, 
        project_idea: str, 
        location: str, 
        capital_str: str, 
        market_summary: str,
        finance_metrics: Dict[str, Any], 
        undocumented: int = 0, 
        total_assumptions: int = 18,
        tracker=None, 
        poll_every: float = 5.0, 
        timeout: float = 300.0
    ) -> Optional[Dict[str, Any]]:
        """متزامن — استدعِه عبر asyncio.to_thread. يعيد {'url','export_url','credits'} أو None."""
        draft_note = (
            "هذه نسخة أولية: بعض الفرضيات غير موثقة. أضف شريحة تحذير واضحة بذلك ولا تستخدم لغة مبالغة.\n"
            if undocumented else ""
        )
        prompt = (
            f"أنشئ عرضاً استثمارياً مختصراً بالعربية الفصحى لمشروع: {project_idea}\n"
            f"الموقع: {location}\nرأس المال المذكور: {capital_str}\n\n"
            "قواعد صارمة: استخدم الأرقام المالية الواردة أدناه فقط، ولا تخترع أي رقم أو مصدر أو حصة سوقية. "
            "ما لا تتوفر له بيانات اكتبه 'يتطلب دراسة ميدانية'.\n"
            f"{draft_note}\n"
            f"الأرقام المعتمدة (من النموذج المالي):\n{self._figures_block(finance_metrics, undocumented, total_assumptions)}\n\n"
            f"ملخص السوق (آلي وغير مؤكد):\n{(market_summary or '')[:1200]}\n\n"
            "الهيكل المطلوب (شريحة لكل بند، والعنوان هو الاستنتاج):\n"
            "1) الغلاف  2) الفرصة والملخص التنفيذي  3) السوق والطلب  4) المشهد التنافسي  "
            "5) الخطة التشغيلية  6) الأداء المالي والعائد  7) استخدام الأموال والمخاطر  8) الخطوات التالية\n---\n"
            "النمط: كحلي داكن مع لمسات ذهبية هادئة، تصميم مؤسسي بسيط."
        )
        payload: Dict[str, Any] = {
            "inputText": prompt, 
            "textMode": "generate", 
            "format": "presentation",
            "numCards": getattr(config, "GAMMA_NUM_CARDS", 8),
            "textOptions": {
                "amount": "medium", 
                "tone": "professional, investor-oriented",
                "audience": "investors and bank credit committees", 
                "language": "ar"
            },
        }
        export_as = getattr(config, "GAMMA_EXPORT_AS", "pdf")
        if export_as in ("pdf", "pptx"):
            payload["exportAs"] = export_as
        
        theme_id = getattr(config, "GAMMA_THEME_ID", None)
        if theme_id:
            payload["themeId"] = theme_id

        try:
            resp = requests.post(f"{BASE}/generations", json=payload, headers=self.headers, timeout=60)
        except requests.RequestException as exc:
            logger.error("تعذر الاتصال بـGamma: %s", exc)
            return None

        if resp.status_code not in (200, 201):
            hint = " (تحقق من المفتاح وأن خطتك تتيح API)" if resp.status_code in (401, 403) else ""
            logger.error("Gamma رفض الطلب %s%s: %s", resp.status_code, hint, resp.text[:300])
            return None

        gen_id = resp.json().get("generationId")
        if not gen_id:
            logger.error("رد Gamma بلا generationId: %s", resp.text[:300])
            return None

        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll_every)
            try:
                st = requests.get(f"{BASE}/generations/{gen_id}", headers=self.headers, timeout=30)
                data = st.json() if st.ok else {}
            except (requests.RequestException, ValueError) as exc:
                logger.warning("خطأ مؤقت أثناء الاستعلام: %s", exc)
                continue

            status = data.get("status")
            if status == "completed":
                credits = (data.get("credits") or {}).get("deducted", 0)
                if tracker:
                    tracker.add_gamma_credits(credits)
                return {"url": data.get("gammaUrl"), "export_url": data.get("exportUrl"), "credits": credits}

            if status == "failed":
                logger.error("فشل توليد Gamma: %s", data)
                return None

        logger.error("انتهت مهلة Gamma (generationId=%s)", gen_id)
        return None
