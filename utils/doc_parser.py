import os
import uuid
import logging
from typing import Tuple
from llama_parse import LlamaParse
import config

logger = logging.getLogger("CastlixDocParser")

async def parse_financial_document(
    file_bytes: bytes, 
    file_name: str, 
    tracker=None
) -> Tuple[str, int]:
    """
    استخراج الجداول والبيانات المالية من ملفات PDF بواسطة LlamaParse
    مع تتبع عدد الصفحات الفعلي وتنظيف الملفات المؤقتة بأمان.
    """
    if not config.LLAMA_CLOUD_API_KEY:
        logger.error("LLAMA_CLOUD_API_KEY غير متوفر في الإعدادات!")
        return "", 0

    # استخدام معرف عشوائي فريد لتجنب تعارض الملفات المؤقتة
    unique_suffix = uuid.uuid4().hex[:8]
    safe_file_name = f"{unique_suffix}_{os.path.basename(file_name)}"
    temp_path = os.path.join("/tmp", safe_file_name)

    try:
        with open(temp_path, "wb") as f:
            f.write(file_bytes)

        parser = LlamaParse(
            api_key=config.LLAMA_CLOUD_API_KEY,
            result_type="markdown",
            verbose=False,
            language="ar",
        )
        
        extra_info = {"file_name": file_name}
        documents = parser.load_data(temp_path, extra_info=extra_info)

        pages_count = len(documents)
        parsed_text = "\n\n".join([doc.text for doc in documents])

        # تسجيل الاستهلاك الفعلي لعدد الصفحات في tracker
        if tracker and pages_count > 0:
            tracker.add_llama_pages(pages_count)

        logger.info(f"تم تحليل {pages_count} صفحة بنجاح من الملف: {file_name}")
        return parsed_text, pages_count

    except Exception as e:
        logger.error(f"خطأ أثناء استخراج البيانات بـ LlamaParse: {e}")
        return "", 0

    finally:
        # إزالة الملف المؤقت فور الانتهاء لضمان الخصوصية
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as err:
                logger.warning(f"تعذر حذف الملف المؤقت {temp_path}: {err}")
