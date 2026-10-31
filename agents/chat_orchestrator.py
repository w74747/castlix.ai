"""
chat_orchestrator.py — منسق الحوار الذكي والاستخلاص الاستشاري لـ Castlix.
يعتمد على بوابة Failover المتعددة لمنع أي انقطاع في الحوار.
"""
import re
import json
import logging
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

from utils.llm_gateway import LLMGateway

logger = logging.getLogger("CastlixChatOrchestrator")


class ProjectIntake(BaseModel):
    is_ready_for_pipeline: bool = Field(description="صحيح إذا توفرت الفكرة والموقع ورأس المال التقريبي")
    project_idea: Optional[str] = Field(None, description="طبيعة ونشاط المشروع")
    location: Optional[str] = Field(None, description="الدولة والمدينة")
    capital: Optional[str] = Field(None, description="الميزانية أو تقدير آلي")
    conversational_reply: str = Field(description="رد مستشار الأعمال الموجه للمستخدم")


SYSTEM_PROMPT = """أنت مستشار استثماري وخبير أعمال في منصة Castlix Advisory.
مهمتك:
1. فهم كلام العميل بأي لهجة عربية (خليجية، عمانية، فصحى، إلخ).
2. استخراج:
   - فكرة المشروع (project_idea)
   - الموقع أو الدولة (location)
   - رأس المال (capital) -> إذا ذكر العميل أنه غير محدد أو لا توجد ميزانية، سجله: "تقدير آلي حسب معايير السوق".
3. إذا اجتمعت لديك الفكرة والموقع (مثل: استخلاص زيت السمسم، والدولة تشاد):
   - اعتبر المتطلبات جاهزة (`is_ready_for_pipeline: true`).
   - اكتب في `conversational_reply` رداً ذكياً يؤكد استيعابك للمشروع وسؤاله لتأكيد الإطلاق.
4. إذا كان هناك نقص جوهري، اسأله عنه بلباقة واجعل `is_ready_for_pipeline: false`.
5. أجب حصراً بصيغة JSON نظيفة مطابقة للمواصفات دون أي مقدمات نصية:
{
  "is_ready_for_pipeline": bool,
  "project_idea": string or null,
  "location": string or null,
  "capital": string or null,
  "conversational_reply": string
}
"""


class ChatOrchestrator:
    def __init__(self):
        self.gateway = LLMGateway()

    def process_user_input(
        self,
        user_message: str,
        current_state: Optional[Dict[str, Any]] = None,
        tracker=None
    ) -> ProjectIntake:
        state = current_state or {}
        context_str = f"المعلومات المتوفرة مسبقاً: {json.dumps(state, ensure_ascii=False)}\n"
        prompt = f"{context_str}رسالة العميل الحالية:\n«{user_message}»"

        try:
            raw = self.gateway.generate_with_failover(
                prompt=prompt,
                system_prompt=SYSTEM_PROMPT,
                tracker=tracker
            )

            # استخراج كائن JSON حتى لو وضع النموذج نصاً قبله أو بعده
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                raw_json = match.group(0)
            else:
                raw_json = raw

            data = json.loads(raw_json)
            
            # دمج البيانات مع الحالة السابقة لضمان عدم ضياع أي معلومة سابقة
            idea = data.get("project_idea") or state.get("project_idea")
            loc = data.get("location") or state.get("location")
            cap = data.get("capital") or state.get("capital")
            
            # إذا توفرت الفكرة والموقع، يعتبر جاهزاً حتى لو نسيه النموذج
            ready = bool(idea and loc)

            return ProjectIntake(
                is_ready_for_pipeline=ready,
                project_idea=idea,
                location=loc,
                capital=cap or "تقدير آلي حسب معايير السوق",
                conversational_reply=data.get("conversational_reply") or "ممتاز، استوعبت الفكرة والموقع وسنبدأ الدراسة."
            )

        except Exception as exc:
            logger.error(f"خطأ أثناء معالجة الحوار: {exc}", exc_info=True)
            
            # استخراج محلي سريع ذكي بدلاً من الرد الجامد المتكرر
            idea = state.get("project_idea") or (user_message if len(user_message) > 15 else None)
            loc = state.get("location") or ("تشاد" if "تشاد" in user_message else None)
            cap = state.get("capital") or "تقدير آلي حسب معايير السوق"
            
            if idea and loc:
                return ProjectIntake(
                    is_ready_for_pipeline=True,
                    project_idea=idea,
                    location=loc,
                    capital=cap,
                    conversational_reply=f"أهلاً بك! تم تسجيل فكرة ({idea}) في ({loc}) برأس مال ({cap})."
                )

            return ProjectIntake(
                is_ready_for_pipeline=False,
                project_idea=idea,
                location=loc,
                capital=cap,
                conversational_reply="أهلاً بك! حدثني باختصار عن فكرة مشروعك والبلد المراد تأسيسه فيه."
            )
