import logging
from typing import Dict, Any, List
from tavily import TavilyClient
import config

logger = logging.getLogger("CastlixMarketAgent")

class MarketResearchAgent:
    def __init__(self):
        if not config.TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY غير موجود في الإعدادات!")
        self.client = TavilyClient(api_key=config.TAVILY_API_KEY)

    def conduct_research(self, project_idea: str, location: str, tracker=None) -> Dict[str, Any]:
        """
        إجراء مسح سوقي متكامل للمنافسين والأسعار وحجم الطلب المحلي.
        """
        logger.info(f"بدء أبحاث السوق لـ: {project_idea} في {location}")
        
        # 1. استعلام المنافسين المباشرين والحصص السوقية
        competitors_query = f"top competitors market share and key players for {project_idea} in {location}"
        
        # 2. استعلام متوسط الأسعار ونماذج التسعير
        pricing_query = f"average pricing cost benchmarks profit margins for {project_idea} in {location}"
        
        # 3. استعلام حجم السوق والطلب المحلي
        demand_query = f"market size growth rate demand trends for {project_idea} industry in {location}"

        queries = [
            ("competitors", competitors_query),
            ("pricing", pricing_query),
            ("demand_and_size", demand_query)
        ]

        research_results = {}

        for key, query in queries:
            try:
                # استخدام البحث المتقدم search_depth="advanced" لضمان عمق التحليل
                response = self.client.search(
                    query=query,
                    search_depth="advanced",
                    max_results=5,
                    include_answer=True,
                    include_raw_content=False
                )
                
                research_results[key] = {
                    "summary_answer": response.get("answer", ""),
                    "sources": [
                        {"title": res.get("title"), "url": res.get("url"), "content": res.get("content")}
                        for res in response.get("results", [])
                    ]
                }
                
                # تحديث عداد التكلفة إذا تم تمريره
                if tracker:
                    tracker.add_tavily(calls=1)

            except Exception as e:
                logger.error(f"خطأ أثناء استدعاء Tavily للبحث عن {key}: {e}")
                research_results[key] = {"summary_answer": "", "sources": []}

        # هيكلة التقرير السوقي النهائي
        formatted_report = self._format_market_findings(research_results, project_idea, location)
        return {
            "raw_data": research_results,
            "structured_report": formatted_report
        }

    def _format_market_findings(self, data: Dict[str, Any], project_idea: str, location: str) -> str:
        """
        صياغة النتائج بتنسيق مهني متوافق مع معايير MECE لبيوت الخبرة.
        """
        comp_summary = data.get("competitors", {}).get("summary_answer", "لم تتوفر ملخصات كافية.")
        pricing_summary = data.get("pricing", {}).get("summary_answer", "تعتمد على متوسطات التكلفة الرأسمالية.")
        demand_summary = data.get("demand_and_size", {}).get("summary_answer", "الطلب مرتبط بمعدلات النمو السكاني والاستثماري.")

        report = (
            f"📊 **تقرير أبحاث السوق الاستراتيجي (Castlix Market Intel)**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• **المشروع المستهدف:** {project_idea}\n"
            f"• **النطاق الجغرافي:** {location}\n\n"
            f"🔍 **1. المشهد التنافسي وأبرز اللاعبين:**\n"
            f"{comp_summary}\n\n"
            f"💰 **2. مؤشرات الأسعار وهيكل التكاليف السائدة:**\n"
            f"{pricing_summary}\n\n"
            f"📈 **3. حجم السوق ومؤشرات الطلب:**\n"
            f"{demand_summary}\n\n"
            f"🔗 **أبرز الروابط والمصادر الموثقة:**\n"
        )

        # استخراج أول 3 روابط موثقة لتغذية سجل الفرضيات
        urls = []
        for cat in data.values():
            for src in cat.get("sources", []):
                if src.get("url") and src.get("url") not in urls:
                    urls.append(src.get("url"))
                    if len(urls) >= 3:
                        break
            if len(urls) >= 3:
                break

        for idx, url in enumerate(urls, 1):
            report += f"  [{idx}] {url}\n"

        return report
