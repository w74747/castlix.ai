import logging
from typing import Dict, Any, Optional
import requests
import config

logger = logging.getLogger("CastlixPresentationAgent")

class PresentationAgent:
    def __init__(self):
        if not config.GAMMA_API_KEY:
            raise ValueError("GAMMA_API_KEY غير موجود في الإعدادات!")
        self.api_key = config.GAMMA_API_KEY
        self.endpoint = "https://api.gamma.app/v1/generations"

    def generate_pitch_deck(
        self,
        project_idea: str,
        location: str,
        capital_str: str,
        market_summary: str,
        tracker=None
    ) -> Optional[Dict[str, str]]:
        """
        إرسال موجه هيكلي لـ Gamma لتوليد عرض شرائح استثماري متكامل.
        """
        logger.info(f"بدء إنشاء عرض المستثمرين التفاعلي لـ: {project_idea} عبر Gamma API...")

        # صياغة محتوى الشرائح وفق هيكل العروض الاستثمارية العالمية (10-12 شريحة)
        structured_prompt = f"""
        أنشئ عرضاً تقديمياً استثمارياً احترافياً (Pitch Deck) موجه للمستثمرين وصناديق التمويل لمشروع: {project_idea}.
        
        الهوية البصرية والنمط:
        - النمط: Corporate, Modern Minimalist, Executive.
        - الألوان المعتمدة: كحلي داكن ملكي، لمسات برونزية/ذهبية، وخلفيات نظيفة.
        - اللغة: العربية الفصحى الاستثمارية.

        معطيات المشروع الأساسية:
        - الموقع الجغرافي: {location}
        - رأس المال التقديري المطلوب: {capital_str}
        - ملخص السوق والمنافسين: {market_summary[:1000]}

        هيكل الشرائح المطلوب بالتفصيل:
        1. شريحة الغلاف: اسم المشروع مع شعار ورؤية "Castlix Strategic Advisory - القلعة الرقمية".
        2. ملخص الفرصة الاستثمارية (Executive Summary): المشكلة في السوق والحل المقترح.
        3. دراسة السوق والطلب: تفكيك حجم السوق (TAM, SAM, SOM) ومحركات النمو.
        4. المشهد التنافسي: مصفوفة المقارنة التنافسية ومكامن التميز.
        5. الخطة التشغيلية والفنية: مراحل التأسيس، الطاقة الإنتاجية، وسلاسل الإمداد.
        6. النموذج المالي والربحية: توقعات الإيرادات لـ 5 سنوات، هوامش EBITDA، ومعدل العائد الداخلي (IRR).
        7. هيكل التمويل واستخدام رأس المال (Use of Funds): تفصيل توزيع الـ CapEx ورأس المال العامل.
        8. خطة إدارة المخاطر واستراتيجية التخارج (Exit Strategy).
        """

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {
            "prompt": structured_prompt,
            "format": "presentation",
            "num_cards": 10,
            "text_language": "ar"
        }

        try:
            response = requests.post(self.endpoint, json=payload, headers=headers, timeout=60)
            
            if response.status_code in [200, 201]:
                data = response.json()
                gamma_url = data.get("url") or data.get("link") or data.get("share_url")
                
                # تتبع التكلفة
                if tracker:
                    tracker.gamma_slides = True

                logger.info(f"تم إنشاء العرض بنجاح: {gamma_url}")
                return {
                    "url": gamma_url,
                    "title": f"Castlix Pitch Deck - {project_idea}"
                }
            else:
                logger.error(f"فشل استدعاء Gamma API: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"خطأ أثناء الاتصال بـ Gamma API: {e}")
            return None
