"""
doc_parser.py — معالجة وقراءة القوائم المالية والملفات المرفوعة (PDF / Excel).

يوفر هذا الملف:
  - تعريف استثناء DocParseError.
  - تنظيف وفحص أسماء الملفات لمنع ثغرات العبور بالمسارات (Path Traversal).
  - استخراج النصوص والجداول من ملفات Excel و PDF بأمان وموثوقية.
"""
import io
import os
import re
import tempfile
import logging
from typing import Tuple

import config

logger = logging.getLogger("CastlixDocParser")


class DocParseError(Exception):
    """استثناء مخصص لأخطاء قراءة وتحليل المستندات."""
    pass


def safe_filename(name: str) -> str:
    """تنظيف اسم الملف من مسارات العبور والرموز غير الآمنة."""
    base = os.path.basename(name.replace("\\", "/"))
    # السماح بالأحرف العربية والإنجليزية والأرقام والنقاط والشرطات
    cleaned = re.sub(r"[^\w\.\-\s\u0600-\u06FF]", "", base).strip()
    return cleaned or "document"


async def parse_financial_document(file_bytes: bytes, filename: str) -> Tuple[str, int]:
    """
    قراءة المستند المستلم (Excel أو PDF) واستخراج محتواه مع عدد الصفحات/الأوراق.
    """
    cleaned_name = safe_filename(filename)
    lower_name = cleaned_name.lower()
    
    # 1. معالجة ملفات Excel
    if lower_name.endswith((".xlsx", ".xls")):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
            text_parts = []
            sheet_count = len(wb.sheetnames)
            
            for sheetname in wb.sheetnames:
                ws = wb[sheetname]
                text_parts.append(f"--- ورقة: {sheetname} ---")
                for row in ws.iter_rows(values_only=True):
                    row_vals = [str(cell) for cell in row if cell is not None]
                    if row_vals:
                        text_parts.append(" | ".join(row_vals))
            
            return "\n".join(text_parts), sheet_count
        except Exception as exc:
            logger.error(f"فشل قراءة ملف الإكسيل: {exc}")
            raise DocParseError(f"تعذر استخراج البيانات من ملف الإكسيل: {exc}")

    # 2. معالجة ملفات PDF
    elif lower_name.endswith(".pdf"):
        # إذا كان LlamaParse مفعلاً في الإعدادات
        if config.LLAMA_CLOUD_API_KEY:
            try:
                from llama_parse import LlamaParse
                parser = LlamaParse(
                    api_key=config.LLAMA_CLOUD_API_KEY,
                    result_type="markdown",
                    verbose=False
                )
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(file_bytes)
                    tmp_path = tmp.name
                
                try:
                    docs = await parser.aload_data(tmp_path)
                    text = "\n\n".join([doc.text for doc in docs])
                    return text, len(docs)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            except Exception as exc:
                logger.warning(f"تعذر استخدام LlamaParse ({exc})؛ سيتم التراجع للمحلل المحلي.")

        # استخراج PDF محلياً كبديل سريع
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            pages = len(reader.pages)
            text = "\n".join([p.extract_text() or "" for p in reader.pages])
            return text, pages
        except ImportError:
            return f"مستند PDF: {cleaned_name} (بحجم {len(file_bytes)/1024:.1f} KB)", 1
        except Exception as exc:
            raise DocParseError(f"تعذر استخراج النصوص من ملف PDF: {exc}")

    else:
        raise DocParseError(f"نوع الملف غير مدعوم ({cleaned_name}). يرجى رفع ملف Excel أو PDF.")
