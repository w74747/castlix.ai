import os
import logging
from llama_parse import LlamaParse
import config

logger = logging.getLogger("CastlixDocParser")

async def parse_financial_document(file_bytes: bytes, file_name: str) -> str:
    """استخراج الجداول والبيانات المالية من ملفات PDF بواسطة LlamaParse"""
    temp_path = f"/tmp/{file_name}"
    with open(temp_path, "wb") as f:
        f.write(file_bytes)

    try:
        parser = LlamaParse(
            api_key=config.LLAMA_CLOUD_API_KEY,
            result_type="markdown",
            verbose=False,
            language="ar",
        )
        extra_info = {"file_name": file_name}
        documents = parser.load_data(temp_path, extra_info=extra_info)
        return "\n\n".join([doc.text for doc in documents])
    except Exception as e:
        logger.error(f"خطأ أثناء استخراج البيانات بـ LlamaParse: {e}")
        return ""
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
