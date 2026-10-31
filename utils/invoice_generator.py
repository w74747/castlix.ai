"""
invoice_generator.py — محرك توليد الفواتير وعروض الأسعار الرسمية (PDF) لمنصة Castlix.

يستخدم هذا المحرك الهوية البصرية المعتمدة في config_branding.py لإنتاج وثائق PDF مهنية
تتضمن بيانات العميل، جدول البنود، الحسابات والضرائب، وإخلاء المسؤولية القانوني.
"""
import io
import datetime
from typing import List, Dict, Any, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

import config_branding as brand


def _hex_to_color(hex_str: str) -> colors.HexColor:
    """تحويل كود اللون السداسي عشري إلى كائن ReportLab Color."""
    clean_hex = hex_str.strip().lstrip("#")
    return colors.HexColor(f"#{clean_hex}")


class InvoiceGenerator:
    """
    مولد وثائق PDF لعروض الأسعار والفواتير المتوافقة مع هوية Castlix.
    """
    def __init__(self):
        self.primary_color = _hex_to_color(brand.COLOR_PRIMARY)
        self.secondary_color = _hex_to_color(brand.COLOR_SECONDARY)
        self.bg_light = _hex_to_color(brand.COLOR_BG_LIGHT)
        self.border_color = _hex_to_color(brand.COLOR_BORDER)
        self.text_color = _hex_to_color(brand.COLOR_TEXT_MAIN)
        self.muted_color = _hex_to_color(brand.COLOR_TEXT_MUTED)

    def generate_document(
        self,
        doc_type: str,  # "INVOICE" أو "QUOTATION"
        doc_number: str,
        client_name: str,
        client_org: str,
        items: List[Dict[str, Any]],  # قائمة قواميس: [{"desc": "...", "qty": 1, "rate": 500.0}]
        currency: str = "USD",
        tax_pct: float = 0.0,
        due_date_days: int = 14,
        notes: Optional[str] = None
    ) -> bytes:
        """
        توليد ملف PDF في الذاكرة وإرجاع البيانات الخام (bytes).
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm
        )

        styles = getSampleStyleSheet()
        
        # تعريف أنماط النصوص المنسجمة مع الهوية
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Normal'],
            fontName=brand.FONT_ENGLISH,
            fontSize=22,
            leading=26,
            textColor=self.primary_color,
            fontBold=True
        )

        subtitle_style = ParagraphStyle(
            'DocSubtitle',
            parent=styles['Normal'],
            fontName=brand.FONT_ENGLISH,
            fontSize=10,
            leading=14,
            textColor=self.muted_color
        )

        normal_style = ParagraphStyle(
            'DocNormal',
            parent=styles['Normal'],
            fontName=brand.FONT_ENGLISH,
            fontSize=10,
            leading=14,
            textColor=self.text_color
        )

        disclaimer_style = ParagraphStyle(
            'DocDisclaimer',
            parent=styles['Normal'],
            fontName=brand.FONT_ENGLISH,
            fontSize=8,
            leading=11,
            textColor=self.muted_color,
            alignment=1  # محاذاة في الوسط
        )

        story = []

        # 1. الترويسة والعنوان (Header)
        doc_title_text = "OFFICIAL INVOICE" if doc_type.upper() == "INVOICE" else "PRICE QUOTATION"
        header_data = [
            [
                Paragraph(f"<b>{brand.COMPANY_NAME_EN}</b><br/>{brand.COMPANY_TAGLINE}", normal_style),
                Paragraph(f"<b>{doc_title_text}</b><br/>#{doc_number}", title_style)
            ]
        ]
        header_table = Table(header_data, colWidths=[10 * cm, 7 * cm])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 1 * cm))

        # 2. بيانات العميل والتاريخ
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        due_str = (datetime.date.today() + datetime.timedelta(days=due_date_days)).strftime("%Y-%m-%d")
        
        meta_data = [
            [
                Paragraph(f"<b>Billed To:</b><br/>{client_name}<br/>{client_org}", normal_style),
                Paragraph(f"<b>Issue Date:</b> {today_str}<br/><b>Valid / Due Date:</b> {due_str}<br/><b>Currency:</b> {currency}", normal_style)
            ]
        ]
        meta_table = Table(meta_data, colWidths=[9 * cm, 8 * cm])
        meta_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), self.bg_light),
            ('BOX', (0, 0), (-1, -1), 0.5, self.border_color),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
            ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ]))
        story.append(meta_table)
        story.append(Spacer(1, 0.8 * cm))

        # 3. جدول البنود والأسعار
        table_rows = [
            ["Item Description", "Qty", f"Rate ({currency})", f"Amount ({currency})"]
        ]
        
        subtotal = 0.0
        for it in items:
            desc = it.get("desc", "")
            qty = float(it.get("qty", 1))
            rate = float(it.get("rate", 0.0))
            amount = qty * rate
            subtotal += amount
            table_rows.append([desc, f"{qty:.0f}", f"{rate:,.2f}", f"{amount:,.2f}"])

        tax_amount = subtotal * (tax_pct / 100.0)
        total = subtotal + tax_amount

        # صفوف المجاميع
        table_rows.append(["", "", "Subtotal:", f"{subtotal:,.2f}"])
        if tax_pct > 0:
            table_rows.append(["", "", f"Tax ({tax_pct:.1f}%):", f"{tax_amount:,.2f}"])
        table_rows.append(["", "", "Total:", f"{total:,.2f}"])

        items_table = Table(table_rows, colWidths=[9.5 * cm, 2 * cm, 2.7 * cm, 2.8 * cm])
        
        t_style = [
            # ترويسة الجدول
            ('BACKGROUND', (0, 0), (-1, 0), self.primary_color),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), brand.FONT_ENGLISH),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, len(items)), 0.5, self.border_color),
            # تلوين المجاميع النهائية
            ('FONTNAME', (2, len(items) + 1), (-1, -1), brand.FONT_ENGLISH),
            ('LINEABOVE', (2, -1), (-1, -1), 1, self.primary_color),
            ('BACKGROUND', (2, -1), (-1, -1), self.secondary_color),
            ('TEXTCOLOR', (2, -1), (-1, -1), colors.white),
            ('FONTSIZE', (2, -1), (-1, -1), 11),
        ]
        items_table.setStyle(TableStyle(t_style))
        story.append(items_table)
        story.append(Spacer(1, 1 * cm))

        # 4. الشروط والملاحظات
        if notes:
            story.append(Paragraph(f"<b>Notes & Payment Instructions:</b><br/>{notes}", normal_style))
            story.append(Spacer(1, 0.8 * cm))

        # 5. إخلاء المسؤولية المعتمد
        story.append(Paragraph(brand.DISCLAIMER_TEXT, disclaimer_style))

        # بناء المستند
        doc.build(story)
        return buffer.getvalue()
