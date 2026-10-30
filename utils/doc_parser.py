import os
from llama_parse import LlamaParse
import config

async def parse_financial_document(file_bytes: bytes, file_name: str) -> str:
    """
    استقبال بايتات الملف وتمريره إلى LlamaParse لاستخراج الجداول والبيانات المالية.
    """
    # حفظ الملف مؤقتاً للمعالجة
    temp_path = f"/tmp/{file_name}"
    with open(temp_path, "wb") as f:
        f.write(file_bytes)
    
    try:
        # إعداد محرك LlamaParse المخصص للمستندات والتقارير المالية
        parser = LlamaParse(
            api_key=config.LLAMA_CLOUD_API_KEY,
            result_type="markdown",  # استخراج الجداول بهيئة Markdown ليفهمها الوكيل بدقة
            verbose=True,
            language="ar",  # دعم اللغة العربية والإنجليزية المزدوجة
        )
        
        # تنفيذ الاستخراج
        extra_info = {"file_name": file_name}
        documents = parser.load_data(temp_path, extra_info=extra_info)
        
        # تجميع النصوص المستخرجة
        parsed_text = "\n\n".join([doc.text for doc in documents])
        return parsed_text

    except Exception as e:
        print(f"Error parsing document with LlamaParse: {e}")
        return ""
    finally:
        # حذف الملف المؤقت للحفاظ على الخصوصية والمساحة
        if os.path.exists(temp_path):
            os.remove(temp_path)
