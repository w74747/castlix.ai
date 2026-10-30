import time
import logging
from typing import Dict, Any, Optional
from e2b_code_interpreter import Sandbox
import config

logger = logging.getLogger("CastlixFinanceAgent")

class FinancialModelingAgent:
    def __init__(self):
        if not config.E2B_API_KEY:
            raise ValueError("E2B_API_KEY غير متوفر!")

    def generate_financial_model(
        self,
        project_idea: str,
        capital_str: str,
        market_data: Dict[str, Any],
        tracker=None
    ) -> Optional[bytes]:
        start_time = time.time()
        logger.info(f"بناء النموذج المالي في سحابة E2B لـ: {project_idea}")

        python_script = '''
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

wb = openpyxl.Workbook()

HEADER_FILL = PatternFill(start_color="0B192C", end_color="0B192C", fill_type="solid")
GOLD_FILL = PatternFill(start_color="C5A880", end_color="C5A880", fill_type="solid")
ZEBRA_FILL = PatternFill(start_color="F5F6F8", end_color="F5F6F8", fill_type="solid")
WHITE_FONT = Font(name="Arial", size=11, bold=True, color="FFFFFF")
BOLD_FONT = Font(name="Arial", size=10, bold=True, color="000000")
REGULAR_FONT = Font(name="Arial", size=10, color="000000")
BLUE_FONT = Font(name="Arial", size=10, bold=True, color="002060")

THIN_BORDER = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)

ws_assumptions = wb.active
ws_assumptions.title = "Assumption_Ledger"
ws_assumptions.views.sheetView[0].showGridLines = True

ws_assumptions["A1"] = "CASTLIX ADVISORY | سجل الفرضيات ومحرك السيناريوهات التفاعلي"
ws_assumptions["A1"].font = Font(name="Arial", size=13, bold=True, color="0B192C")

ws_assumptions["B3"] = "السيناريو النشط (Active Case):"
ws_assumptions["B3"].font = BOLD_FONT
ws_assumptions["C3"] = "Base Case"
ws_assumptions["C3"].font = Font(name="Arial", size=11, bold=True, color="002060")
ws_assumptions["C3"].fill = GOLD_FILL
ws_assumptions["C3"].alignment = Alignment(horizontal="center")

ws_assumptions["B4"] = "مؤشر السيناريو (Case ID):"
ws_assumptions["B4"].font = BOLD_FONT
ws_assumptions["C4"] = '=MATCH(C3, {"Base Case", "Downside Case", "Upside Case"}, 0)'
ws_assumptions["C4"].font = BOLD_FONT
ws_assumptions["C4"].alignment = Alignment(horizontal="center")

headers = [
    "الكود (ID)", "بيان الفرضية", "وحدة القياس",
    "الحالة 1: الأساس", "الحالة 2: المتحفظ", "الحالة 3: المتفائل",
    "العمود النشط (Active)", "مصدر التوثيق (Source)"
]

for col_idx, h in enumerate(headers, 1):
    c = ws_assumptions.cell(row=6, column=col_idx, value=h)
    c.fill = HEADER_FILL
    c.font = WHITE_FONT
    c.alignment = Alignment(horizontal="center", vertical="center")

assumptions_data = [
    ("MAC-01", "معدل التضخم السنوي", "%", 0.03, 0.045, 0.02, "World Bank / Central Bank"),
    ("CAP-01", "إجمالي النفقات الرأسمالية (CapEx)", "$", 500000, 600000, 450000, "Tavily Industrial Benchmark"),
    ("REV-01", "حجم المبيعات / الإنتاج (سنة 1)", "وحدة", 10000, 7500, 13000, "Castlix Market Feasibility"),
    ("REV-02", "سعر بيع الوحدة الأساسي", "$", 85.0, 72.0, 95.0, "Competitive Pricing Survey"),
    ("OPX-01", "التكلفة المتغيرة للوحدة", "$", 38.0, 44.0, 32.0, "Sec-Edgar / Industry Average"),
    ("OPX-02", "المصروفات التشغيلية الثابتة", "$", 120000, 140000, 105000, "Operational Budget Benchmark"),
    ("FIN-01", "سعر الفائدة على التمويل (WACC)", "%", 0.08, 0.095, 0.07, "FMP Capital Benchmark")
]

for r_idx, row in enumerate(assumptions_data, 7):
    for c_idx, val in enumerate(row[:6], 1):
        cell = ws_assumptions.cell(row=r_idx, column=c_idx, value=val)
        cell.font = BLUE_FONT if c_idx in [4, 5, 6] else REGULAR_FONT
        cell.border = THIN_BORDER
        if "%" in str(row[2]) and isinstance(val, (int, float)):
            cell.number_format = '0.0%'
        elif "$" in str(row[2]) and isinstance(val, (int, float)):
            cell.number_format = '#,##0'

    active_cell = ws_assumptions.cell(row=r_idx, column=7, value=f'=CHOOSE($C$4, D{r_idx}, E{r_idx}, F{r_idx})')
    active_cell.font = BOLD_FONT
    active_cell.border = THIN_BORDER
    active_cell.fill = ZEBRA_FILL
    if "%" in str(row[2]):
        active_cell.number_format = '0.0%'
    elif "$" in str(row[2]):
        active_cell.number_format = '#,##0'

    src_cell = ws_assumptions.cell(row=r_idx, column=8, value=row[6])
    src_cell.font = Font(name="Arial", size=9, italic=True, color="595959")
    src_cell.border = THIN_BORDER

ws_model = wb.create_sheet(title="Financial_Forecast")
ws_model.views.sheetView[0].showGridLines = True

ws_model["A1"] = "التوقعات المالية لخمس سنوات (Five-Year Projections)"
ws_model["A1"].font = Font(name="Arial", size=13, bold=True, color="0B192C")

timeline_headers = ["بند القائمة المالية ($)", "سنة 1", "سنة 2", "سنة 3", "سنة 4", "سنة 5"]
for col_idx, h in enumerate(timeline_headers, 1):
    c = ws_model.cell(row=3, column=col_idx, value=h)
    c.fill = HEADER_FILL
    c.font = WHITE_FONT
    c.alignment = Alignment(horizontal="center")

financial_rows = [
    ("إجمالي الإيرادات (Gross Revenue)", "=Assumption_Ledger!G9*Assumption_Ledger!G10", "=B4*(1+Assumption_Ledger!$G$7)"),
    ("التكاليف المتغيرة (Variable Costs)", "=Assumption_Ledger!G9*Assumption_Ledger!G11", "=B5*(1+Assumption_Ledger!$G$7)"),
    ("المصاريف الثابتة (Fixed OpEx)", "=Assumption_Ledger!G12", "=B6*(1+Assumption_Ledger!$G$7)"),
    ("الربح التشغيلي قبل الإهلاك (EBITDA)", "=B4-B5-B6", "=C4-C5-C6"),
    ("صافي التدفق النقدي الحر (FCF)", "=B7", "=C7")
]

for idx, (label, y1_formula, proj_formula) in enumerate(financial_rows, 4):
    lbl_cell = ws_model.cell(row=idx, column=1, value=label)
    lbl_cell.font = BOLD_FONT
    lbl_cell.border = THIN_BORDER

    y1_cell = ws_model.cell(row=idx, column=2, value=y1_formula)
    y1_cell.font = BOLD_FONT
    y1_cell.number_format = '#,##0'
    y1_cell.border = THIN_BORDER

    for c_idx in range(3, 7):
        prev_col = get_column_letter(c_idx - 1)
        curr_col = get_column_letter(c_idx)
        dyn_formula = proj_formula.replace("B", prev_col).replace("C", curr_col) if "B" in proj_formula else proj_formula
        cell = ws_model.cell(row=idx, column=c_idx, value=dyn_formula)
        cell.font = BOLD_FONT
        cell.number_format = '#,##0'
        cell.border = THIN_BORDER

for ws in [ws_assumptions, ws_model]:
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

wb.save("/tmp/Castlix_Financial_Model.xlsx")
'''
        try:
            with Sandbox(api_key=config.E2B_API_KEY) as sandbox:
                execution = sandbox.commands.run(f"python3 -c '{python_script}'")
                if execution.error:
                    logger.error(f"خطأ في تنفيذ كود E2B: {execution.error}")
                    return None

                file_bytes = sandbox.files.read("/tmp/Castlix_Financial_Model.xlsx", format="bytes")
                if tracker:
                    duration = int(time.time() - start_time)
                    tracker.add_e2b_duration(seconds=max(duration, 15))
                    tracker.fmp_calls += 1

                logger.info("تم بناء وتحميل ملف الإكسيل بنجاح.")
                return file_bytes
        except Exception as e:
            logger.error(f"فشل تشغيل بيئة E2B: {e}")
            return None
