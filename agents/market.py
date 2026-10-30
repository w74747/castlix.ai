import logging
from typing import Dict, Any
from tavily import TavilyClient
import config

logger = logging.getLogger("CastlixMarketAgent")

class MarketResearchAgent:
    def __init__(self):
        if not config.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY غير متوفر!")
        self.client = TavilyClient(api_key=config.TAVILY_API_KEY)

    def conduct_research(self, project_idea: str, location: str, tracker=None) -> Dict[str, Any]:
        logger.info(f"بدء استعلامات السوق لـ: {project_idea} في {location}")
        queries = [
            ("competitors", f"top competitors market share and key players for {project_idea} in {location}"),
            ("pricing", f"average pricing cost benchmarks profit margins for {project_idea} in {location}"),
            ("demand_and_size", f"market size growth rate demand trends for {project_idea} industry in {location}")
        ]

        research_results = {}
        for key, query in queries:
            try:
                response = self.client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=4,
                    include_answer=True
                )
                research_results[key] = {
                    "summary_answer": response.get("answer", ""),
                    "sources": [
                        {"title": res.get("title"), "url": res.get("url")}
                        for res in response.get("results", [])
                    ]
                }
                if tracker:
                    tracker.add_tavily(calls=1)
            except Exception as e:
                logger.error(f"خطأ أثناء بحث Tavily عن {key}: {e}")
                research_results[key] = {"summary_answer": "", "sources": []}

        formatted_report = self._format_market_findings(research_results, project_idea, location)
        return {"raw_data": research_results, "structured_report": formatted_report}

    def _format_market_findings(self, data: Dict[str, Any], project_idea: str, location: str) -> str:
        comp_summary = data.get("competitors", {}).get("summary_answer", "لا تتوفر تفاصيل كافية.")
        pricing_summary = data.get("pricing", {}).get("summary_answer", "تعتمد على متوسطات التكلفة القياسية.")
        demand_summary = data.get("demand_and_size", {}).get("summary_answer", "مرتبط بمعدل النمو الاستثماري للقطاع.")

        report = (
            f"📊 **تقرير مسح السوق الاستراتيجي (Castlix Market Intel)**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **المشروع المستهدف:** {project_idea}\n"
            f"• **النطاق الجغرافي:** {location}\n\n"
            f"🔍 **1. المشهد التنافسي وأبرز المنافسين:**\n"
            f"{comp_summary}\n\n"
            f"💰 **2. مؤشرات الأسعار وهيكل التكاليف:**\n"
            f"{pricing_summary}\n\n"
            f"📈 **3. حجم السوق ومؤشرات الطلب:**\n"
            f"{demand_summary}\n\n"
            f"🔗 **أبرز المصادر والروابط المسترجعة:**\n"
        )

        urls = []
        for cat in data.values():
            for src in cat.get("sources", []):
                u = src.get("url")
                if u and u not in urls:
                    urls.append(u)
                    if len(urls) >= 3:
                        break
            if len(urls) >= 3:
                break

        for idx, u in enumerate(urls, 1):
            report += f"  [{idx}] {u}\n"

        return report
