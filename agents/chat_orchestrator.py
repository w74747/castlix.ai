"""
chat_orchestrator.py — منسق الحوار الذكي والاستخلاص الاستشاري لـ Castlix.

الوظيفة:
  * إدارة الحوار بطريقة تفاعلية استشارية بأسلوب بشري غير متكلف.
  * فهم اللهجات المحلية (عمانية، خليجية، شامية، مصرية) والفصحى.
  * استخراج بيانات المشروع الأساسية (الفكرة، الموقع، رأس المال) في صورة كائن منظم.
  * مساعدة العميل على صياغة الفكرة واستكمال المعطيات قبل تشغيل محرك النمذجة.
"""
import json
import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from utils.llm_gateway import LLMGateway
import config

logger = logging.getLogger("CastlixChatOrchestrator")


class ProjectIntake(BaseModel):
    is_ready_for_pipeline: bool = Field(
        description="صحيح (True) إذا كانت الفكرة والموقع ورأس المال مفهومة بشكل كافٍ لبدء النموذج المالي، وإلا فخطأ (False)"
    )
    project_idea: Optional[str] = Field(None, description="طبيعة ونشاط المشروع المستخلص بدقة")
    location: Optional[str] = Field(None, description="الدولة والمدينة أو المنطقة الصناعية")
    capital: Optional[str] = Field(None, description="رأس المال المبدئي أو عبارة تقدير آلي إن لم يحدده")
    conversational_reply: str = Field(
        description="رد مستشار الأعمال الموجه للمستخدم؛ يرحب به، أو يناقشه، أو يسأله عن النواقص بلباقة"
    )


EXTRACTION_SYSTEM_PROMPT = """أنت مستشار استثماري وشريك أعمال خبير في منصة Castlix Advisory.
مهمتك:
1. التحدث بلباقة ونبرة استشارية راقية، وفهم كلام العميل مهما كانت لهجته (عمانية، خليجية، فصحى، إلخ).
2. استخلاص ثلاثة أركان رئيسية لبناء دراسة الجدوى:
   - فكرة المشروع وطبيعته (Project Idea).
   - الموقع الجغرافي أو المنطقة الصناعية (Location).
   - رأس المال المبدئي التقريبي أو رغبة العميل في أن يقدره النظام آلياً (Capital).
3. إذا دمج العميل كل شيء في رسالة واحدة (مثلاً: "باغي افتح كافيه في بوشر بميزانية عشرين ألف ريال"):
   - استخرج القيم وضع `is_ready_for_pipeline: true`.
   - اجعل `conversational_reply` يؤكد استيعابك للمعطيات ويسأله تأكيد الإطلاق.
4. إذا نقصت معطيات (مثل غياب الموقع أو رأس المال)، اسأله عنها بسلاسة وود واجعل `is_ready_for_pipeline: false`.
5. يجب أن يكون ردك دائماً كائن JSON حصراً مطابقاً للحقول التالية دون مقدمات:
{
  "is_ready_for_pipeline": bool,
  "project_idea": string or null,
  "location": string or null,
  "capital": string or null,
  "conversational_reply": string
}
"""


class ChatOrchestrator:
    def __init__(self, provider: str = "xai", model: Optional[str] = None):
        self.gateway = LLMGateway()
        # المزود الافتراضي للحوار؛ يمكن استخدام xai (Grok) أو claude أو deepseek
        self.provider = provider
        self.model = model

    def process_user_input(
        self,
        user_message: str,
        current_state: Optional[Dict[str, Any]] = None,
        tracker=None
    ) -> ProjectIntake:
        """
        معالجة رسالة العميل واستخلاص المعطيات بذكاء.
        """
        context_text = f"المعطيات الحالية المسجلة مسبقاً إن وجدت: {json.dumps(current_state or {}, ensure_ascii=False)}\n"
        prompt = f"{context_text}رسالة العميل الأخيرة:\n«{user_message}»"

        try:
            raw_response = self.gateway.generate(
                prompt=prompt,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                provider=self.provider,
                model=self.model,
                temperature=0.3,
                max_tokens=1000,
                tracker=tracker
            )

            # تنظيف وسوم الماركداون المحتملة إن وجدت في رد النموذج
            cleaned = raw_response.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)
            return ProjectIntake(**data)

        except Exception as exc:
            logger.warning(f"تعذر استخراج JSON من LLM ({exc})، تفعيل الرد الاحتياطي.")
            # رد احتياطي مباشر في حال حدوث أي خطأ في النموذج الخارجي
            return ProjectIntake(
                is_ready_for_pipeline=False,
                project_idea=(current_state or {}).get("project_idea"),
                location=(current_state or {}).get("location"),
                capital=(current_state or {}).get("capital"),
                conversational_reply="أهلاً بك! يرجى توضيح فكرة مشروعك، والدولة أو المدينة المقترحة، ورأس المال المتاح للبدء."
            )
