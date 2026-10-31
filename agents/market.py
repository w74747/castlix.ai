"""
market.py — وكيل أبحاث السوق عبر Tavily (نسخة مصححة وموثقة).

التحسينات الجوهرية:
  * دعم استعلامات باللغتين العربية والإنجليزية.
  * خيار حصر النطاقات الجغرافية عبر MARKET_INCLUDE_DOMAINS في الإعدادات.
  * تتبع حقيقي لاستهلاك الكريدتس في Tavily.
  * مخرجات مهيكلة مع وسم الملخصات الآلية بأنها "غير مؤكدة" لضمان المصداقية الاستثمارية.
  * تهريب النصوص (HTML Escaping) لضمان عدم تعطل رسائل تليجرام.
"""
import logging
from typing import Any, Dict, List, Optional

from tavily import TavilyClient
import config
from utils.telegram_text import esc

logger = logging.getLogger("CastlixMarketAgent")

CATEGORIES = [
    ("competitors", "🔍 المشهد التنافسي وأبرز المنافسين", "competitors market share players"),
    ("pricing", "💰 مؤشرات الأسعار وهيكل التكاليف السائدة", "pricing cost breakdown margins average price"),
    ("demand_and_size", "📈 حجم السوق ومؤشرات الطلب والنمو", "market size growth rate demand trends"),
]


class MarketResearchAgent:
    def __init__(self):
        if not config.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY غير متوفر في متغيرات البيئة!")
        self.client = TavilyClient(api_key=config.TAVILY_API_KEY)
        self.include_domains = getattr(config, "MARKET_INCLUDE_DOMAINS", [])

    def conduct_research(
        self,
        project_idea: str,
        location: str,
        tracker=None
    ) -> Dict[str, Any]:
        """
        إجراء مسح سوقي ميداني عبر استعلامات مخصصة مع تسجيل دقيق للاستهلاك.
        """
        logger.info(f"بدء استعلامات مسح السوق لـ: {project_idea} في {location}")
        
        research_results = {}
        total_sources_count = 0

        for key, title_ar, query_en in CATEGORIES:
            # دمج المصطلحات العربية والإنجليزية لضمان تغطية المصادر المحلية والإقليمية
            composed_query = f"{project_idea} in {location} {query_en}"
            
            search_kwargs: Dict[str, Any] = {
                "query": composed_query,
                "search_depth": "advanced",
                "max_results": 4,
                "include_answer": True,
            }
            
            if self.include_domains:
                search_kwargs["include_domains"] = self.include_domains

            try:
                response = self.client.search(**search_kwargs)
                
                # تسجيل استدعاء حقيقي في عداد التكلفة
                if tracker:
                    tracker.add_tavily(calls=1)

                answer = response.get("answer", "")
                raw_results = response.get("results", [])
                
                sources = []
                for item in raw_results:
                    url = item.get("url", "")
                    title = item.get("title", "")
                    content = item.get("content", "")
                    if url:
                        sources.append({
                            "title": title,
                            "url": url,
                            "snippet": content[:300] if content else "",
                        })
                
                total_sources_count += len(sources)
                research_results[key] = {
                    "category_title": title_ar,
                    "summary_answer": answer,
                    "sources": sources,
                }

            except Exception as e:
                logger.error(f"خطأ أثناء استعلام Tavily عن {key}: {e}")
                research_results[key] = {
                    "category_title": title_ar,
                    "summary_answer": "",
                    "sources": [],
                    "error": str(e),
                }

        formatted_report = self._format_findings_html(research_results, project_idea, location)
        
        return {
            "raw_data": research_results,
            "structured_report": formatted_report,
            "total_sources_found": total_sources_count,
        }

    def _format_findings_html(
        self, 
        data: Dict[str, Any], 
        project_idea: str, 
        location: str
    ) -> str:
        """
        صياغة النتائج بتنسيق HTML آمن لرسائل تليجرام مع التمييز بين التقدير والتوثيق.
        """
        lines = [
            "📊 <b>تقرير مسح السوق الميداني (Castlix Market Intel)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"• <b>المشروع:</b> {esc(project_idea)}",
            f"• <b>النطاق الجغرافي:</b> {esc(location)}",
            "",
        ]

        collected_urls = []

        for key, _, _ in CATEGORIES:
            cat_data = data.get(key, {})
            title = cat_data.get("category_title", key)
            answer = cat_data.get("summary_answer", "").strip()
            sources = cat_data.get("sources", [])

            lines.append(f"<b>{title}</b>")
            
            if answer:
                # توضيح صريح بأن هذا الملخص آلي أولي لضمان الشفافية
                lines.append(f"<i>(مؤشر أولي):</i> {esc(answer)}")
            else:
                lines.append("<i>لم يُعثر على ملخص مباشر من المصادر المتاحة.</i>")
            
            lines.append("")

            for s in sources:
                u = s.get("url")
                if u and u not in collected_urls and len(collected_urls) < 4:
                    collected_urls.append((s.get("title") or u, u))

        if collected_urls:
            lines.append("🔗 <b>المصادر والروابط المسترجعة:</b>")
            for idx, (t, u) in enumerate(collected_urls, 1):
                safe_title = esc(t[:40]) + ("..." if len(t) > 40 else "")
                lines.append(f"  [{idx}] <a href=\"{esc(u)}\">{safe_title}</a>")
        else:
            lines.append("⚠️ <i>تنبيه: لم يتم استرجاع روابط موثقة مباشرة، وتتطلب الأرقام تدقيقاً ميدانياً.</i>")

        return "\n".join(lines)
