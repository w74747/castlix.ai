import logging
from typing import Dict, Optional
import requests
import config

logger = logging.getLogger("CastlixPresentationAgent")

class PresentationAgent:
    def __init__(self):
        if not config.GAMMA_API_KEY:
            raise ValueError("GAMMA_API_KEY غير متوفر!")
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
        logger.info(f"بدء توليد شرائح Gamma لـ: {project_idea}")

        structured_prompt = f"""
        أنشئ عرضاً تقديمياً استثمارياً احترافياً (Pitch Deck) موجه للمستثمرين وصناديق التمويل لمشروع: {project_idea}.
        الهوية البصرية والنمط:
        - النمط: Corporate, Modern Minimalist, Executive.
        - الألوان: كحلي داكن ملكي، لمسات برونزية/ذهبية، وخلفيات رمادية فاتحة ونظيفة.
        - اللغة: العربية الفصحى الاستثمارية.

        معطيات المشروع:
        - الموقع الجغرافي: {location}
        - رأس المال المرصود: {capital_str}
        - ملخص السوق والمنافسين: {market_summary[:900]}

        هيكل الشرائح المطلوب:
        1. شريحة الغلاف: شعار وهوية "Castlix Strategic Advisory - القلعة الرقمية".
        2. ملخص الفرصة الاستثمارية (Executive Summary).
        3. دراسة حجم السوق ومحركات النمو (TAM, SAM, SOM).
        4. المشهد التنافسي ونقاط القوة التمايزية.
        5. الخطة التشغيلية وسلاسل الإمداد.
        6. التوقعات المالية وهوامش الربحية لـ 5 سنوات.
        7. هيكل استخدام رأس المال (Use of Funds).
        8. إدارة المخاطر وخطة التخارج (Exit Strategy).
        """

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "prompt": structured_prompt,
            "format": "presentation",
            "num_cards": 8,
            "text_language": "ar"
        }

        try:
            response = requests.post(self.endpoint, json=payload, headers=headers, timeout=60)
            if response.status_code in [200, 201]:
                data = response.json()
                gamma_url = data.get("url") or data.get("link") or data.get("share_url")
                if tracker:
                    tracker.gamma_slides = True
                return {"url": gamma_url, "title": f"Castlix Pitch Deck - {project_idea}"}
            else:
                logger.error(f"خطأ استجابة Gamma API: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"استثناء أثناء استدعاء Gamma: {e}")
            return None
