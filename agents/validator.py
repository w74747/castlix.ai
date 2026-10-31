import logging
from typing import Dict, Any, List

logger = logging.getLogger("CastlixValidator")

class QAValidationEngine:
    """
    محرك التدقيق والتحقق المستقل (Independent QA & Cross-Validation)
    """
    @staticmethod
    def validate_feasibility_inputs(
        market_data: Dict[str, Any],
        capacity_units: int,
        projected_sales_units: int
    ) -> List[str]:
        errors = []
        
        # 1. فحص الاتساق بين الطاقة الإنتاجية وتوقعات السوق
        if projected_sales_units > capacity_units:
            errors.append(
                f"تعارض جوهري: حجم المبيعات المتوقع ({projected_sales_units:,}) "
                f"يتجاوز الطاقة الاستيعابية القصوى المحددة ({capacity_units:,})!"
            )
            
        # 2. فحص وجود مصادر معتمدة لأبحاث السوق
        sources = []
        for cat in market_data.get("raw_data", {}).values():
            sources.extend(cat.get("sources", []))
            
        if not sources:
            errors.append("نقص توثيق: وكيل السوق لم يقدم أي روابط مصادر صلبة للتحقق منها.")
            
        return errors
