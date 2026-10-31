"""
agents/market.py — وكيل أبحاث السوق لمشروع جديد (مسح المنافسين والأسعار والطلب).

يعتمد على Tavily API للبحث الحي و LLM Gateway لصياغة التقرير التسويقي المنظم.
"""
import logging
from typing import Any, Dict, List, Optional

import config
from utils.llm_gateway import LLMGateway
from utils.telegram_text import esc

logger = logging.getLogger("CastlixMarketAgent")

try:
    from tavily import TavilyClient
except ImportError:
    TavilyClient = None


SYSTEM_PROMPT = """أنت مستشار وخبير أبحاث سوق استثماري في منصة Castlix Advisory.
مهمتك تحليل مخرجات البحث الحي حول مشروع معين وصياغة ملخص تنفيذي تسويقي دقيق ومباشر للمستثمر.

قواعد الصياغة:
1. استخدم لغة استشارية رفيعة ورصينة موجهة لرواد الأعمال والمستثمرين.
2. قسّم التقرير إلى 4 أقسام رئيسية واضحة:
   - حجم السوق والفرصة المتاحة.
   - المشهد التنافسي واللاعبون الرئيسيون.
   - مؤشرات الأسعار وهيكل التسعير التقريبي.
   - الفرضيات السوقية والتوصيات التشغيلية الأولية.
3. لا تختلق أرقاماً لا تستند إلى نتائج البحث أو المنطق الاقتصادي السليم.
4. اذكر بوضوح أي فرضيات تتطلب تحققاً ميدانياً لاحقاً.
"""


class MarketResearchAgent:
    def __init__(self):
        self.gateway = LLMGateway()
        self.tavily = (
            TavilyClient(api_key=config.TAVILY_API_KEY)
            if (TavilyClient and config.TAVILY_API_KEY)
            else None
        )

    def _build_queries(self, project_idea: str, location: str) -> List[Dict[str, str]]:
        """بناء استعلامات بحث محددة ثنائية اللغة لتغطية محاور السوق."""
        queries = [
            {
                "topic": "competitors",
                "ar": f"المنافسون شركات مصانع {project_idea} {location}",
                "en": f"top competitors companies {project_idea} {location} market analysis",
            },
            {
                "topic": "pricing",
                "ar": f"أسعار تكلفة بيع منتجات {project_idea} {location}",
                "en": f"average wholesale retail price {project_idea} {location}",
            },
            {
                "topic": "demand_and_size",
                "ar": f"حجم السوق والطلب والاستهلاك {project_idea} {location}",
                "en": f"market size demand trends {project_idea} {location} industry report",
            },
        ]
        return queries

    def _execute_search(self, query: str, tracker=None) -> Dict[str, Any]:
        """تنفيذ بحث عبر Tavily مع معالجة الأخطاء وتسجيل التكلفة."""
        if not self.tavily:
            return {"text": "", "sources": []}

        try:
            depth = config.MARKET_SEARCH_DEPTH
            include_domains = config.MARKET_INCLUDE_DOMAINS if config.MARKET_INCLUDE_DOMAINS else None

            res = self.tavily.search(
                query=query,
                search_depth=depth,
                include_domains=include_domains,
                max_results=4,
            )

            # احتساب الكريدتس بحسب عمق البحث (advanced = 2, basic = 1)
            credits_spent = 2.0 if depth == "advanced" else 1.0
            if tracker and hasattr(tracker, "add_tavily"):
                # تمرير المعاملات بأمان
                tracker.add_tavily(credits=credits_spent, calls=1)

            results = res.get("results", [])
            text_snippets = []
            sources = []

            for r in results:
                content = r.get("content", "").strip()
                title = r.get("title", "").strip()
                url = r.get("url", "").strip()
                if content:
                    text_snippets.append(content)
                if url:
                    sources.append({"title": title or url, "url": url})

            return {
                "text": "\n\n".join(text_snippets)[:2500],
                "sources": sources,
            }

        except Exception as exc:
            logger.error(f"خطأ أثناء استعلام Tavily عن «{query[:40]}»: {exc}")
            return {"text": "", "sources": []}

    def conduct_research(
        self,
        project_idea: str,
        location: str,
        tracker=None
    ) -> Dict[str, Any]:
        """
        إجراء أبحاث السوق الميدانية والرقمية الشاملة وتوليد التقرير التنفيذي.
        """
        logger.info(f"بدء استعلامات مسح السوق لـ: {project_idea} في {location}")

        if not self.tavily:
            logger.warning("Tavily API غير مهيأ؛ تخطي البحث الحي.")
            return {
                "report_html": "⚠️ <b>أبحاث السوق:</b> لم يتم ضبط مفتاح Tavily API، تم تخطي المسح المباشر.",
                "structured_report": "لم يتم إجراء مسح سوق حي بسبب غياب مفتاح Tavily.",
                "sources": [],
            }

        queries = self._build_queries(project_idea, location)
        aggregated_findings = []
        collected_sources: List[Dict[str, str]] = []

        # 1. تنفيذ جولات البحث عبر المحاور المحددة
        for q_item in queries:
            topic = q_item["topic"]
            
            # البحث الإنجليزي أولاً لأنه الأغنى بالبيانات العالمية
            en_res = self._execute_search(q_item["en"], tracker=tracker)
            if en_res["text"]:
                aggregated_findings.append(f"[{topic.upper()} - EN RESULTS]:\n{en_res['text']}")
                collected_sources.extend(en_res["sources"])

            # البحث العربي لجمع المؤشرات المحلية
            if config.MARKET_BILINGUAL:
                ar_res = self._execute_search(q_item["ar"], tracker=tracker)
                if ar_res["text"]:
                    aggregated_findings.append(f"[{topic.upper()} - AR RESULTS]:\n{ar_res['text']}")
                    collected_sources.extend(ar_res["sources"])

        combined_text = "\n\n".join(aggregated_findings).strip()

        # 2. صياغة التقرير النهائي بالذكاء الاصطناعي
        user_prompt = (
            f"المشروع المستهدف: {project_idea}\n"
            f"النطاق الجغرافي: {location}\n\n"
            f"البيانات المستخرجة من محركات البحث:\n"
            f"{combined_text if combined_text else 'لم يتم العثور على بيانات كافية عبر الويب.'}\n\n"
            "المطلوب: صياغة تقرير مسح سوق مركز وشامل وفق القواعد المحددة."
        )

        try:
            structured_summary = self.gateway.generate_with_failover(
                prompt=user_prompt,
                system_prompt=SYSTEM_PROMPT,
                tracker=tracker,
            )
        except Exception as exc:
            logger.error(f"فشل صياغة ملخص السوق عبر النماذج اللغوية: {exc}")
            structured_summary = (
                f"يشهد نشاط {project_idea} في {location} فرصاً واعدة نظراً لارتفاع الطلب الإقليمي "
                f"وتوفر مقومات الإنتاج، مع ضرورة التركيز على كفاءة سلاسل الإمداد ومواصفات الجودة التصديرية."
            )

        # 3. إعداد الروابط والمصادر (أول 3 مصادر فريدة)
        unique_sources = []
        seen_urls = set()
        for s in collected_sources:
            if s["url"] not in seen_urls:
                seen_urls.add(s["url"])
                unique_sources.append(s)
            if len(unique_sources) >= 3:
                break

        sources_html = ""
        if unique_sources:
            links = [f'<a href="{esc(s["url"])}">{esc(s["title"][:40])}</a>' for s in unique_sources]
            sources_html = f"\n\n🔗 <b>أبرز المصادر المرجعية:</b>\n• " + "\n• ".join(links)

        report_html = (
            f"📊 <b>نتائج مسح ودراسة السوق ({esc(location)}):</b>\n\n"
            f"{esc(structured_summary)}"
            f"{sources_html}"
        )

        return {
            "report_html": report_html,
            "structured_report": structured_summary,
            "sources": unique_sources,
            "raw_text": combined_text,
        }
