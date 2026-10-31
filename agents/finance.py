"""
finance.py — وكيل النمذجة المالية (نسخة مُصحّحة).

ما تغيّر عن النسخة السابقة:
  * لا E2B ولا `python -c '...'`: القالب ثابت ومُختبر ويُبنى محلياً بـ openpyxl (أرخص وأسرع وبلا أخطاء اقتباس).
  * الصيغ مُولَّدة بمراجع صريحة لكل عمود (لا استبدال نصي متسلسل) فلا مراجع دائرية.
  * نموذج حقيقي: إيراد ← EBITDA ← إهلاك ← دين وفوائد ← ضريبة ← رأس مال عامل ← تدفقات حرة،
    مع NPV وIRR وفترة الاسترداد وDSCR ونقطة التعادل وقيمة نهائية.
  * سجل الفرضيات صادق: كل فرضية لها مصدر ومستوى ثقة وتاريخ. ما لم يُوثَّق يُوسم "Low" بوضوح،
    ولا تُنسب أي قيمة إلى مصدر لم تُؤخذ منه.
  * ورقة Sensitivity (سيناريوهات + شبكة سعر×حجم + Tornado) تُحسب بنسخة بايثون مطابقة ومختبرة.
  * ورقة Checks تفحص سلامة النموذج، وSummary تعرض تحذيراً صريحاً ما دامت هناك فرضيات غير موثقة.
"""
from __future__ import annotations

import datetime as _dt
import io
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from agents.finance_core import HORIZON, Params, grid_price_volume, run_model, tornado

logger = logging.getLogger("CastlixFinanceAgent")

# ---------------------------------------------------------------------------
# تحويل العملات إلى دولار (ربط رسمي تقريبي)
# ---------------------------------------------------------------------------
FX_TO_USD = {"USD": 1.0, "OMR": 2.6008, "SAR": 1 / 3.75, "AED": 1 / 3.6725}

PLACEHOLDER_SOURCE = "افتراض افتراضي للنموذج الأولي — لم يُوثَّق بعد"

# ---------------------------------------------------------------------------
# الهوية البصرية (Castlix)
# ---------------------------------------------------------------------------
NAVY, GOLD, GREY, SOFT = "0B192C", "C5A880", "F5F6F8", "FFF8E1"
FONT = "Arial"
F_TITLE = Font(name=FONT, size=14, bold=True, color=NAVY)
F_HDR = Font(name=FONT, size=10, bold=True, color="FFFFFF")
F_BOLD = Font(name=FONT, size=10, bold=True, color="000000")
F_TXT = Font(name=FONT, size=10, color="000000")
F_IN = Font(name=FONT, size=10, color="0000FF")          # مدخلات
F_LINK = Font(name=FONT, size=10, color="008000")        # روابط بين الأوراق
F_NOTE = Font(name=FONT, size=9, italic=True, color="595959")
FILL_HDR = PatternFill("solid", start_color=NAVY)
FILL_GOLD = PatternFill("solid", start_color=GOLD)
FILL_GREY = PatternFill("solid", start_color=GREY)
FILL_KEY = PatternFill("solid", start_color="FFFF00")    # مدخل رئيسي
FILL_WARN = PatternFill("solid", start_color="FDE9E7")
_thin = Side(style="thin", color="D9D9D9")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)

NF_USD = '#,##0;(#,##0);"-"'
NF_PCT = '0.0%;(0.0%);"-"'
NF_NUM = '#,##0.0;(#,##0.0);"-"'
NF_INT = "0"
NF_X = '0.00"x"'
NF_YR = '0.0" سنة"'


# ---------------------------------------------------------------------------
# نموذج الفرضيات
# ---------------------------------------------------------------------------
@dataclass
class Assumption:
    key: str
    id: str
    label: str
    unit: str
    base: float
    down: float
    up: float
    fmt: str                      # usd | pct | num | int
    source: str = PLACEHOLDER_SOURCE
    confidence: str = "Low"       # High | Medium | Low
    date: str = field(default_factory=lambda: _dt.date.today().isoformat())
    key_input: bool = False


ORDER = [
    "capex", "capacity", "util_y1", "util_step", "util_max", "price", "price_growth",
    "var_cost", "fixed_opex", "inflation", "wacc", "debt_share", "interest", "tenor",
    "tax", "dep_life", "nwc_pct", "terminal_g"
]
FIRST_ROW = 8
ROW = {k: FIRST_ROW + i for i, k in enumerate(ORDER)}
LAST_ROW = FIRST_ROW + len(ORDER) - 1


def A(key: str) -> str:
    """مرجع القيمة الفعّالة (عمود Active) لفرضية ما."""
    return f"Assumptions!$G${ROW[key]}"


def parse_capital(text: Optional[str]) -> Tuple[Optional[float], str]:
    """
    يستخرج رأس المال بالدولار من نص حر. يعيد (القيمة أو None، ملاحظة المصدر).
    يدعم: أرقام عربية/هندية، فواصل، مليون/ألف/M/K، دولار/ريال عماني/ريال سعودي/درهم.
    """
    if not text:
        return None, "لم يُحدَّد رأس المال"
    t = text.strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩٬٫،", "0123456789,.,"))
    low = t.lower()
    if any(w in low for w in ("ابحث", "لا أعلم", "لا اعلم", "search")):
        return None, "طُلب من النظام تقدير رأس المال"
    m = re.search(r"(\d[\d,]*\.?\d*)", t)
    if not m:
        return None, "لم يُفهم رقم رأس المال"
    num = float(m.group(1).replace(",", ""))
    if re.search(r"مليار|billion|\bb\b", low):
        num *= 1e9
    elif re.search(r"مليون|million|\bm\b|\dm\b", low):
        num *= 1e6
    elif re.search(r"ألف|الف|\bk\b|\dk\b|thousand", low):
        num *= 1e3
    ccy, note = "USD", "دولار"
    if re.search(r"عماني|omr|ر\.?\s?ع|rial", low):
        ccy, note = "OMR", "ريال عماني"
    elif re.search(r"سعودي|sar", low):
        ccy, note = "SAR", "ريال سعودي"
    elif re.search(r"درهم|aed", low):
        ccy, note = "AED", "درهم إماراتي"
    elif "ريال" in low:
        ccy, note = "OMR", "ريال (افتُرض عمانياً — تأكد)"
    usd = num * FX_TO_USD[ccy]
    return usd, f"مدخل المستخدم: «{text.strip()}» ({note}) ← {usd:,.0f} دولار"


def default_assumptions(
    capex_usd: Optional[float], 
    capex_note: str,
    overrides: Optional[Dict[str, Dict[str, Any]]] = None
) -> List[Assumption]:
    """
    فرضيات أولية مُقاسة على رأس المال. كلها placeholders بثقة Low، عدا رأس المال إن أدخله المستخدم.
    """
    user_capex = capex_usd is not None and capex_usd > 0
    C = float(capex_usd) if user_capex else 500_000.0
    price = 100.0
    capacity = round(1.2 * C / price, -1) or 10.0
    lib = [
        Assumption("capex", "CAP-01", "إجمالي النفقات الرأسمالية (CapEx) — تُصرف في السنة 0", "USD",
                   C, C * 1.20, C * 0.90, "usd",
                   source=capex_note if user_capex else f"{PLACEHOLDER_SOURCE} (500,000 دولار)",
                   confidence="Medium" if user_capex else "Low", key_input=True),
        Assumption("capacity", "REV-01", "الطاقة الإنتاجية السنوية عند 100% استغلال", "وحدة/سنة",
                   capacity, capacity, capacity, "usd"),
        Assumption("util_y1", "REV-02", "استغلال الطاقة في السنة 1", "%", 0.55, 0.45, 0.65, "pct", key_input=True),
        Assumption("util_step", "REV-03", "الزيادة السنوية في الاستغلال", "نقطة مئوية", 0.10, 0.07, 0.12, "pct"),
        Assumption("util_max", "REV-04", "سقف الاستغلال", "%", 0.90, 0.80, 0.95, "pct"),
        Assumption("price", "REV-05", "سعر بيع الوحدة (السنة 1)", "USD/وحدة", price, price * 0.90, price * 1.08, "num", key_input=True),
        Assumption("price_growth", "MAC-01", "نمو السعر السنوي", "%", 0.02, 0.01, 0.03, "pct"),
        Assumption("var_cost", "OPX-01", "التكلفة المتغيرة للوحدة (السنة 1)", "USD/وحدة", 55.0, 60.0, 52.0, "num", key_input=True),
        Assumption("fixed_opex", "OPX-02", "المصروفات التشغيلية الثابتة (السنة 1)", "USD/سنة",
                   0.12 * C, 0.132 * C, 0.11 * C, "usd"),
        Assumption("inflation", "MAC-02", "تضخم التكاليف السنوي", "%", 0.03, 0.045, 0.025, "pct"),
        Assumption("wacc", "FIN-01", "معدل الخصم (WACC)", "%", 0.10, 0.12, 0.09, "pct", key_input=True),
        Assumption("debt_share", "FIN-02", "نسبة التمويل بالدين من CapEx", "%", 0.50, 0.50, 0.50, "pct"),
        Assumption("interest", "FIN-03", "سعر الفائدة على الدين", "%", 0.07, 0.085, 0.065, "pct"),
        Assumption("tenor", "FIN-04", "مدة سداد الدين (أقساط أصل متساوية)", "سنة", 5, 5, 5, "int"),
        Assumption("tax", "FIN-05", "معدل ضريبة الدخل (تحقق من الشريحة المنطبقة)", "%", 0.15, 0.15, 0.15, "pct"),
        Assumption("dep_life", "FIN-06", "العمر الإنتاجي للإهلاك (قسط ثابت)", "سنة", 10, 10, 10, "int"),
        Assumption("nwc_pct", "FIN-07", "رأس المال العامل كنسبة من الإيراد", "%", 0.10, 0.12, 0.08, "pct"),
        Assumption("terminal_g", "FIN-08", "نمو القيمة النهائية (Gordon)", "%", 0.02, 0.01, 0.025, "pct"),
    ]
    by_key = {a.key: a for a in lib}
    for key, ov in (overrides or {}).items():
        a = by_key.get(key)
        if not a:
            logger.warning("override لمفتاح غير معروف: %s", key)
            continue
        for fld in ("base", "down", "up", "source", "confidence", "date"):
            if fld in ov:
                setattr(a, fld, ov[fld])
        if "base" in ov and "down" not in ov:
            a.down = a.up = ov["base"]
    return lib


def params_for(assumptions: List[Assumption], scenario: str = "base") -> Params:
    pick = {"base": "base", "down": "down", "up": "up"}[scenario]
    v = {a.key: getattr(a, pick) for a in assumptions}
    return Params(
        capex=v["capex"], capacity=v["capacity"], util_y1=v["util_y1"], util_step=v["util_step"],
        util_max=v["util_max"], price=v["price"], price_growth=v["price_growth"],
        var_cost=v["var_cost"], fixed_opex=v["fixed_opex"], inflation=v["inflation"],
        wacc=v["wacc"], debt_share=v["debt_share"], interest=v["interest"], tenor=int(v["tenor"]),
        tax=v["tax"], dep_life=int(v["dep_life"]), nwc_pct=v["nwc_pct"], terminal_g=v["terminal_g"],
    )


# ---------------------------------------------------------------------------
# مساعدات التنسيق
# ---------------------------------------------------------------------------
def _hdr(ws, row: int, values: List[str], start_col: int = 1) -> None:
    for i, v in enumerate(values):
        c = ws.cell(row=row, column=start_col + i, value=v)
        c.font, c.fill, c.border = F_HDR, FILL_HDR, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _fmt_for(kind: str) -> str:
    return {"usd": NF_USD, "pct": NF_PCT, "num": NF_NUM, "int": NF_INT}[kind]


def _put(ws, ref: str, value, font=F_TXT, fmt: Optional[str] = None, fill=None, bold=False,
         align: Optional[str] = None, border=True):
    c = ws[ref]
    c.value = value
    c.font = Font(name=font.name, size=font.size, bold=bold or font.bold, italic=font.italic, color=font.color)
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if border:
        c.border = BORDER
    if align:
        c.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
    return c


# ---------------------------------------------------------------------------
# بناء الأوراق
# ---------------------------------------------------------------------------
def _sheet_assumptions(wb: Workbook, items: List[Assumption], project: str) -> None:
    ws = wb.active
    ws.title = "Assumptions"
    ws.sheet_view.rightToLeft = True
    ws["A1"].value = "CASTLIX ADVISORY | سجل الفرضيات ومحرك السيناريوهات"
    ws["A1"].font = F_TITLE
    ws["A2"].value = f"المشروع: {project}"
    ws["A2"].font = F_NOTE

    _put(ws, "B3", "السيناريو النشط (Active Case):", F_BOLD)
    _put(ws, "C3", "Base", F_IN, fill=FILL_GOLD, bold=True, align="center")
    dv = DataValidation(type="list", formula1='"Base,Downside,Upside"', allow_blank=False)
    dv.error, dv.errorTitle = "اختر Base أو Downside أو Upside", "قيمة غير صالحة"
    ws.add_data_validation(dv)
    dv.add("C3")
    _put(ws, "B4", "مؤشر السيناريو (Case ID):", F_BOLD)
    _put(ws, "C4", '=IF(C3="Base",1,IF(C3="Downside",2,IF(C3="Upside",3,1)))', F_TXT, align="center")
    ws["D3"].value = "← اختر السيناريو من القائمة؛ يتحدث النموذج بالكامل."
    ws["D3"].font = F_NOTE
    ws["A5"].value = ("دليل الألوان: أزرق = مدخل يُعدَّل · أسود = صيغة · أخضر = ربط بين أوراق · "
                      "أصفر = مدخل رئيسي. الثقة Low = لم تُوثَّق بعد.")
    ws["A5"].font = F_NOTE

    _hdr(ws, 7, ["ID", "الفرضية", "الوحدة", "Base", "Downside", "Upside", "Active", "المصدر / سلسلة التدقيق",
                 "الثقة", "التاريخ"])
    for a in items:
        r = ROW[a.key]
        fmt = _fmt_for(a.fmt)
        _put(ws, f"A{r}", a.id, F_TXT)
        _put(ws, f"B{r}", a.label, F_TXT)
        _put(ws, f"C{r}", a.unit, F_TXT, align="center")
        for col, val in (("D", a.base), ("E", a.down), ("F", a.up)):
            _put(ws, f"{col}{r}", val, F_IN, fmt, fill=FILL_KEY if (a.key_input and col == "D") else None)
        _put(ws, f"G{r}", f"=CHOOSE($C$4,D{r},E{r},F{r})", F_BOLD, fmt, fill=FILL_GREY)
        _put(ws, f"H{r}", a.source, F_NOTE)
        _put(ws, f"I{r}", a.confidence, F_IN, align="center")
        _put(ws, f"J{r}", a.date, F_NOTE, align="center")
    dv2 = DataValidation(type="list", formula1='"High,Medium,Low"', allow_blank=False)
    ws.add_data_validation(dv2)
    dv2.add(f"I{FIRST_ROW}:I{LAST_ROW}")
    ws.conditional_formatting.add(f"I{FIRST_ROW}:I{LAST_ROW}",
                                  CellIsRule(operator="equal", formula=['"Low"'], fill=FILL_WARN))
    for col, w in zip("ABCDEFGHIJ", (10, 52, 14, 14, 14, 14, 14, 58, 10, 12)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "D8"


YEAR_COLS = ["C", "D", "E", "F", "G", "H"]  # السنة 0..5
R = dict(util=6, vol=7, price=8, rev=9, vcu=10, varc=11, fixed=12, ebitda=13, margin=14, dep=15, ebit=16,
         d_open=17, repay=18, d_close=19, interest=20, ebt=21, tax=22, ni=23, nwc=24, dnwc=25, capex=26,
         utax=27, fcf=28, tv=29, fcf_tv=30, df=31, pv=32, pv_tv=33, cum=34, pb=35, cfads=36, ds=37,
         dscr=38, eq=39)

LABELS = {
    "util": ("استغلال الطاقة", "%"), "vol": ("حجم المبيعات", "وحدة"), "price": ("سعر الوحدة", "USD"),
    "rev": ("الإيرادات", "USD"), "vcu": ("التكلفة المتغيرة للوحدة", "USD"), "varc": ("التكاليف المتغيرة", "USD"),
    "fixed": ("المصروفات الثابتة", "USD"), "ebitda": ("EBITDA", "USD"), "margin": ("هامش EBITDA", "%"),
    "dep": ("الإهلاك", "USD"), "ebit": ("EBIT", "USD"), "d_open": ("الدين — رصيد أول المدة", "USD"),
    "repay": ("سداد أصل الدين", "USD"), "d_close": ("الدين — رصيد آخر المدة", "USD"),
    "interest": ("الفوائد", "USD"), "ebt": ("الربح قبل الضريبة", "USD"), "tax": ("الضريبة (بعد الفوائد)", "USD"),
    "ni": ("صافي الربح", "USD"), "nwc": ("رأس المال العامل (رصيد)", "USD"),
    "dnwc": ("التغير في رأس المال العامل", "USD"), "capex": ("النفقات الرأسمالية", "USD"),
    "utax": ("الضريبة على EBIT (غير مرفّعة)", "USD"), "fcf": ("التدفق الحر للمشروع (Unlevered FCF)", "USD"),
    "tv": ("القيمة النهائية (Gordon)", "USD"), "fcf_tv": ("التدفق الحر شاملاً القيمة النهائية", "USD"),
    "df": ("معامل الخصم", "x"), "pv": ("القيمة الحالية للتدفق", "USD"), "pv_tv": ("القيمة الحالية للقيمة النهائية", "USD"),
    "cum": ("التدفق التراكمي", "USD"), "pb": ("مساعد: جزء سنة الاسترداد", "سنة"),
    "cfads": ("التدفق المتاح لخدمة الدين (CFADS)", "USD"), "ds": ("خدمة الدين (فوائد + أصل)", "USD"),
    "dscr": ("نسبة تغطية خدمة الدين (DSCR)", "x"), "eq": ("التدفق لحملة الأسهم", "USD"),
}
ROW_FMT = {"util": NF_PCT, "vol": NF_USD, "price": NF_NUM, "vcu": NF_NUM, "margin": NF_PCT, "df": "0.0000",
           "dscr": NF_X, "pb": "0.00"}
BOLD_ROWS = {"rev", "ebitda", "ebit", "ni", "fcf", "fcf_tv", "cfads", "eq", "dscr"}


def _sheet_model(wb: Workbook) -> None:
    ws = wb.create_sheet("Model")
    ws.sheet_view.rightToLeft = True
    ws["A1"].value = "النموذج المالي — خمس سنوات تشغيل (USD)"
    ws["A1"].font = F_TITLE
    ws["A2"].value = '=Assumptions!C3&" — السيناريو النشط"'
    ws["A2"].font = F_NOTE
    _hdr(ws, 4, ["البند", "الوحدة"] + ["السنة 0"] + [f"السنة {i}" for i in range(1, HORIZON + 1)])
    _put(ws, "A5", "فهرس السنة", F_NOTE)
    for i, col in enumerate(YEAR_COLS):
        _put(ws, f"{col}5", i, F_NOTE, NF_INT, align="center")

    for key, row in R.items():
        label, unit = LABELS[key]
        _put(ws, f"A{row}", label, F_BOLD if key in BOLD_ROWS else F_TXT)
        _put(ws, f"B{row}", unit, F_NOTE, align="center")

    for i, col in enumerate(YEAR_COLS):
        prev = YEAR_COLS[i - 1] if i > 0 else None
        t = f"{col}$5"
        g = {}
        if i == 0:
            g["capex"] = f"={A('capex')}"
            g["d_close"] = f"={A('capex')}*{A('debt_share')}"
            g["nwc"] = 0
            g["fcf"] = f"=-{col}{R['capex']}"
            g["tv"] = 0
            g["eq"] = f"=-{col}{R['capex']}+{col}{R['d_close']}"
            g["cum"] = f"={col}{R['fcf']}"
        else:
            g["util"] = f"=MIN({A('util_max')},{A('util_y1')}+({t}-1)*{A('util_step')})"
            g["vol"] = f"={A('capacity')}*{col}{R['util']}"
            g["price"] = f"={A('price')}*(1+{A('price_growth')})^({t}-1)"
            g["rev"] = f"={col}{R['vol']}*{col}{R['price']}"
            g["vcu"] = f"={A('var_cost')}*(1+{A('inflation')})^({t}-1)"
            g["varc"] = f"={col}{R['vol']}*{col}{R['vcu']}"
            g["fixed"] = f"={A('fixed_opex')}*(1+{A('inflation')})^({t}-1)"
            g["ebitda"] = f"={col}{R['rev']}-{col}{R['varc']}-{col}{R['fixed']}"
            g["margin"] = f"=IF({col}{R['rev']}=0,0,{col}{R['ebitda']}/{col}{R['rev']})"
            g["dep"] = f"=IF({t}<={A('dep_life')},{A('capex')}/{A('dep_life')},0)"
            g["ebit"] = f"={col}{R['ebitda']}-{col}{R['dep']}"
            g["d_open"] = f"={prev}{R['d_close']}"
            g["repay"] = f"=IF({t}<={A('tenor')},MIN({col}{R['d_open']},$C${R['d_close']}/{A('tenor')}),0)"
            g["d_close"] = f"={col}{R['d_open']}-{col}{R['repay']}"
            g["interest"] = f"={col}{R['d_open']}*{A('interest')}"
            g["ebt"] = f"={col}{R['ebit']}-{col}{R['interest']}"
            g["tax"] = f"=MAX(0,{col}{R['ebt']})*{A('tax')}"
            g["ni"] = f"={col}{R['ebt']}-{col}{R['tax']}"
            g["nwc"] = f"={col}{R['rev']}*{A('nwc_pct')}"
            g["dnwc"] = f"={col}{R['nwc']}-{prev}{R['nwc']}"
            g["capex"] = 0
            g["utax"] = f"=MAX(0,{col}{R['ebit']})*{A('tax')}"
            g["fcf"] = f"={col}{R['ebitda']}-{col}{R['utax']}-{col}{R['dnwc']}-{col}{R['capex']}"
            g["tv"] = (f"=IF({A('wacc')}>{A('terminal_g')},{col}{R['fcf']}*(1+{A('terminal_g')})"
                       f"/({A('wacc')}-{A('terminal_g')}),0)") if i == HORIZON else 0
            g["cum"] = f"={prev}{R['cum']}+{col}{R['fcf']}"
            g["pb"] = (f"=IF(AND({prev}{R['cum']}<0,{col}{R['cum']}>=0),({t}-1)+(-{prev}{R['cum']})/{col}{R['fcf']},0)")
            g["cfads"] = f"={col}{R['ebitda']}-{col}{R['tax']}-{col}{R['dnwc']}"
            g["ds"] = f"={col}{R['interest']}+{col}{R['repay']}"
            g["dscr"] = f'=IF({col}{R["ds"]}=0,"-",{col}{R["cfads"]}/{col}{R["ds"]})'
            g["eq"] = f"={col}{R['cfads']}-{col}{R['interest']}-{col}{R['repay']}"
        g["fcf_tv"] = f"={col}{R['fcf']}+{col}{R['tv']}"
        g["df"] = f"=1/(1+{A('wacc')})^{t}"
        g["pv"] = f"={col}{R['fcf']}*{col}{R['df']}"
        g["pv_tv"] = f"={col}{R['tv']}*{col}{R['df']}"

        for key, val in g.items():
            ref = f"{col}{R[key]}"
            is_link = isinstance(val, str) and re.fullmatch(r"=Assumptions!\$G\$\d+", val) is not None
            _put(ws, ref, val, F_LINK if is_link else F_TXT, ROW_FMT.get(key, NF_USD),
                 bold=key in BOLD_ROWS, align="right")

    for key in ("ebitda", "fcf", "eq"):
        for col in ["A", "B"] + YEAR_COLS:
            ws[f"{col}{R[key]}"].fill = FILL_GREY
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 9
    for col in YEAR_COLS:
        ws.column_dimensions[col].width = 15
    ws.freeze_panes = "C6"


def _sheet_checks(wb: Workbook) -> None:
    ws = wb.create_sheet("Checks")
    ws.sheet_view.rightToLeft = True
    ws["A1"].value = "فحوصات سلامة النموذج"
    ws["A1"].font = F_TITLE
    _hdr(ws, 3, ["الفحص", "النتيجة"])
    last_col = YEAR_COLS[-1]
    checks = [
        ("النفقات الرأسمالية > 0", f'=IF({A("capex")}>0,"OK","CHECK")'),
        ("الاستغلال بين 0 و100% في كل السنوات",
         f'=IF(AND(MAX(Model!D{R["util"]}:{last_col}{R["util"]})<=1,MIN(Model!D{R["util"]}:{last_col}{R["util"]})>=0),"OK","CHECK")'),
        ("سعر الوحدة أعلى من التكلفة المتغيرة للوحدة في كل سنة",
         f'=IF(SUMPRODUCT(--(Model!D{R["price"]}:{last_col}{R["price"]}<=Model!D{R["vcu"]}:{last_col}{R["vcu"]}))=0,"OK","CHECK")'),
        ("معدل الخصم أكبر من نمو القيمة النهائية", f'=IF({A("wacc")}>{A("terminal_g")},"OK","CHECK")'),
        ("نسبة الدين بين 0 و100%", f'=IF(AND({A("debt_share")}>=0,{A("debt_share")}<=1),"OK","CHECK")'),
        ("مدة السداد والإهلاك ≥ 1 سنة", f'=IF(AND({A("tenor")}>=1,{A("dep_life")}>=1),"OK","CHECK")'),
        ("الدين لا يصبح سالباً", f'=IF(MIN(Model!C{R["d_close"]}:{last_col}{R["d_close"]})>=-0.5,"OK","CHECK")'),
        ("الدين مسدد بالكامل خلال الأفق إن كانت المدة ≤ 5",
         f'=IF({A("tenor")}<={HORIZON},IF(ABS(Model!{last_col}{R["d_close"]})<0.5,"OK","CHECK"),"OK")'),
        ("خلو الأوراق من أخطاء الصيغ", f'=IF(SUMPRODUCT(--ISERROR(Model!C6:{last_col}{R["eq"]}))=0,"OK","CHECK")'),
    ]
    for i, (label, f) in enumerate(checks, start=4):
        _put(ws, f"A{i}", label, F_TXT)
        _put(ws, f"B{i}", f, F_BOLD, align="center")
    end = 3 + len(checks)
    ws.conditional_formatting.add(f"B4:B{end}", CellIsRule(operator="equal", formula=['"CHECK"'], fill=FILL_WARN))
    _put(ws, f"A{end + 2}", "الحالة العامة", F_BOLD)
    _put(ws, f"B{end + 2}", f'=IF(COUNTIF(B4:B{end},"CHECK")=0,"ALL OK","CHECK ("&COUNTIF(B4:B{end},"CHECK")&")")',
         F_BOLD, fill=FILL_GOLD, align="center")
    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 16
    wb._castlix_overall = f"Checks!$B${end + 2}"  # type: ignore[attr-defined]


def _sheet_summary(wb: Workbook, project: str, location: str, capital_note: str) -> None:
    ws = wb.create_sheet("Summary", 0)
    ws.sheet_view.rightToLeft = True
    last = YEAR_COLS[-1]
    ws["A1"].value = "CASTLIX ADVISORY | الملخص التنفيذي للنموذج المالي"
    ws["A1"].font = F_TITLE
    ws["A2"].value = f"المشروع: {project}  |  الموقع: {location}"
    ws["A2"].font = F_NOTE
    total = len(ORDER)
    rng = f"Assumptions!$I${FIRST_ROW}:$I${LAST_ROW}"
    ws.merge_cells("A3:C3")
    _put(ws, "A3",
         f'=IF(B20>0,"⚠ نموذج أولي: "&B20&" من {total} فرضية غير موثقة — لا يُستخدم للتمويل أو القرار قبل توثيقها",'
         f'"✔ جميع الفرضيات موثقة بمستوى ثقة Medium أو أعلى")',
         F_BOLD, fill=FILL_WARN, border=False)
    ws.row_dimensions[3].height = 32
    ws["A3"].alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")

    _hdr(ws, 4, ["المؤشر", "القيمة", "ملاحظة"])
    rows = [
        (5, "صافي القيمة الحالية NPV — 5 سنوات بدون قيمة نهائية", f"=SUM(Model!C{R['pv']}:{last}{R['pv']})", NF_USD, "مجموع التدفقات المخصومة"),
        (6, "صافي القيمة الحالية NPV — شاملاً القيمة النهائية", f"=B5+SUM(Model!C{R['pv_tv']}:{last}{R['pv_tv']})", NF_USD, "Gordon على تدفق السنة 5"),
        (7, "IRR المشروع — 5 سنوات بدون قيمة نهائية", f'=IFERROR(IRR(Model!C{R["fcf"]}:{last}{R["fcf"]}),"n/a")', NF_PCT, "n/a = لا يوجد تغيّر إشارة"),
        (8, "IRR المشروع — شاملاً القيمة النهائية", f'=IFERROR(IRR(Model!C{R["fcf_tv"]}:{last}{R["fcf_tv"]}),"n/a")', NF_PCT, "قارنه بمعدل الخصم"),
        (9, "IRR حملة الأسهم", f'=IFERROR(IRR(Model!C{R["eq"]}:{last}{R["eq"]}),"n/a")', NF_PCT, "بعد الدين والفوائد"),
        (10, "فترة الاسترداد (سنة)", f'=IF(SUM(Model!D{R["pb"]}:{last}{R["pb"]})=0,"> 5",SUM(Model!D{R["pb"]}:{last}{R["pb"]}))', "0.0", "بدون قيمة نهائية"),
        (11, "أدنى DSCR", f'=IF(COUNT(Model!D{R["dscr"]}:{last}{R["dscr"]})=0,"n/a",MIN(Model!D{R["dscr"]}:{last}{R["dscr"]}))', NF_X, "البنوك تطلب عادة ≥ 1.2–1.3x"),
        (12, "متوسط DSCR", f'=IF(COUNT(Model!D{R["dscr"]}:{last}{R["dscr"]})=0,"n/a",AVERAGE(Model!D{R["dscr"]}:{last}{R["dscr"]}))', NF_X, ""),
        (13, "هامش EBITDA — السنة 3", f"=Model!F{R['margin']}", NF_PCT, ""),
        (14, "إجمالي النفقات الرأسمالية", f"={A('capex')}", NF_USD, capital_note),
        (15, "الاستغلال اللازم لتعادل EBITDA (أسعار السنة 1)",
         f'=IF({A("price")}>{A("var_cost")},{A("fixed_opex")}/(({A("price")}-{A("var_cost")})*{A("capacity")}),"n/a")', NF_PCT, "نقطة تعادل تشغيلية"),
        (16, "معدل الخصم المستخدم", f"={A('wacc')}", NF_PCT, ""),
        (17, "السيناريو النشط", "=Assumptions!C3", None, "غيّره من ورقة Assumptions"),
        (18, "حالة فحوصات السلامة", f"={wb._castlix_overall}", None, "راجع ورقة Checks"),  # type: ignore[attr-defined]
        (19, "الإشارة الأولية",
         '=IF(B20>0,"غير قابلة للحكم — توثيق ناقص",IF(NOT(ISNUMBER(B8)),"تحتاج مراجعة",'
         'IF(AND(B6>0,B8>B16,IF(ISNUMBER(B11),B11>=1.25,TRUE)),"إيجابية مبدئياً","تحتاج مراجعة")))', None, "لا تُعتمد دون مراجعة بشرية"),
        (20, "عدد الفرضيات غير الموثقة (Low)", f'=COUNTIF({rng},"Low")', NF_INT, ""),
    ]
    for r, label, formula, fmt, note in rows:
        is_link = isinstance(formula, str) and re.fullmatch(r"=(Assumptions|Checks)![\$A-Z0-9]+", formula) is not None
        _put(ws, f"A{r}", label, F_TXT)
        _put(ws, f"B{r}", formula, F_LINK if is_link else F_BOLD, fmt, align="center")
        _put(ws, f"C{r}", note, F_NOTE)
    ws["B6"].fill = FILL_GOLD
    ws["B8"].fill = FILL_GOLD
    ws["B19"].fill = FILL_GOLD

    notes = [
        "حدود النموذج (للقارئ المتخصص):",
        "• تدفقات سنوية؛ الإنفاق الرأسمالي كله في السنة 0؛ لا فترة سماح ولا ترحيل خسائر ضريبية.",
        "• القيمة النهائية بطريقة Gordon وتشكّل غالباً نسبة كبيرة من NPV — اقرأ NPV بدونها أيضاً.",
        "• ورقة Sensitivity قيم ثابتة محسوبة بنسخة بايثون مطابقة؛ لا تتحدث عند تعديل الفرضيات يدوياً.",
        "• هذا النموذج أداة تحليل أولية ولا يُعدّ استشارة مالية أو قانونية أو ضريبية.",
    ]
    for i, n in enumerate(notes, start=22):
        ws[f"A{i}"].value = n
        ws[f"A{i}"].font = F_BOLD if i == 22 else F_NOTE
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 46


def _sheet_sensitivity(wb: Workbook, items: List[Assumption]) -> Dict[str, Any]:
    ws = wb.create_sheet("Sensitivity")
    ws.sheet_view.rightToLeft = True
    ws["A1"].value = "السيناريوهات والحساسية"
    ws["A1"].font = F_TITLE
    ws["A2"].value = ("قيم ثابتة محسوبة بنسخة بايثون مطابقة لمنطق الصيغ (مختبَرة) وقت إصدار الملف — "
                      "لا تتحدث عند تعديل الفرضيات. أعد توليد الملف بعد أي تعديل جوهري.")
    ws["A2"].font = F_NOTE

    scen = {}
    for name, key in (("Base", "base"), ("Downside", "down"), ("Upside", "up")):
        scen[name] = run_model(params_for(items, key))["metrics"]

    _hdr(ws, 4, ["المؤشر", "Base", "Downside", "Upside"])
    lines = [
        ("NPV شاملاً القيمة النهائية (USD)", "npv_tv", NF_USD),
        ("NPV بدون قيمة نهائية (USD)", "npv_explicit", NF_USD),
        ("IRR المشروع شاملاً القيمة النهائية", "irr_tv", NF_PCT),
        ("IRR حملة الأسهم", "irr_equity", NF_PCT),
        ("فترة الاسترداد (سنة)", "payback", "0.0"),
        ("أدنى DSCR", "min_dscr", NF_X),
        ("إيراد السنة 5 (USD)", "revenue_y5", NF_USD),
        ("EBITDA السنة 5 (USD)", "ebitda_y5", NF_USD),
    ]
    for i, (label, key, fmt) in enumerate(lines, start=5):
        _put(ws, f"A{i}", label, F_TXT)
        for col, name in zip("BCD", ("Base", "Downside", "Upside")):
            v = scen[name][key]
            _put(ws, f"{col}{i}", v if v is not None else ("> 5" if key == "payback" else "n/a"),
                 F_TXT, fmt, align="right")

    base_p = params_for(items, "base")
    g = grid_price_volume(base_p)
    r0 = 5 + len(lines) + 2
    ws[f"A{r0}"].value = "شبكة NPV (شاملاً القيمة النهائية) — سعر البيع (صفوف) × حجم المبيعات (أعمدة)، سيناريو Base"
    ws[f"A{r0}"].font = F_BOLD
    _hdr(ws, r0 + 1, ["سعر \\ حجم"] + [f"{s:+.0%}" for s in g["steps"]])
    for i, (ps, row) in enumerate(zip(g["steps"], g["values"])):
        rr = r0 + 2 + i
        _put(ws, f"A{rr}", f"{ps:+.0%}", F_BOLD, align="center")
        for j, v in enumerate(row):
            _put(ws, f"{get_column_letter(2 + j)}{rr}", v, F_TXT, NF_USD)
    ws.conditional_formatting.add(
        f"B{r0 + 2}:{get_column_letter(1 + len(g['steps']))}{r0 + 1 + len(g['steps'])}",
        CellIsRule(operator="lessThan", formula=["0"], fill=FILL_WARN))

    t0 = r0 + 2 + len(g["steps"]) + 2
    tor = tornado(base_p)
    ws[f"A{t0}"].value = "Tornado — أثر ±10% (ومعدل الخصم ±1 نقطة) على NPV، مرتبة بالأثر"
    ws[f"A{t0}"].font = F_BOLD
    _hdr(ws, t0 + 1, ["المتغير", "NPV (حالة سيئة)", "NPV (حالة جيدة)", "نطاق التأرجح"])
    for i, row in enumerate(tor):
        rr = t0 + 2 + i
        _put(ws, f"A{rr}", row["label"], F_TXT)
        _put(ws, f"B{rr}", row["low"], F_TXT, NF_USD)
        _put(ws, f"C{rr}", row["high"], F_TXT, NF_USD)
        _put(ws, f"D{rr}", row["swing"], F_BOLD, NF_USD)
    ws.column_dimensions["A"].width = 46
    for col in "BCDEF":
        ws.column_dimensions[col].width = 18
    return {"scenarios": scen, "tornado": tor}


# ---------------------------------------------------------------------------
# الوكيل
# ---------------------------------------------------------------------------
@dataclass
class FinanceResult:
    file_bytes: bytes
    metrics: Dict[str, Any]           # مؤشرات سيناريو Base
    scenarios: Dict[str, Dict[str, Any]]
    undocumented: int
    total_assumptions: int
    warnings: List[str]
    capital_usd: float


class FinancialModelingAgent:
    """متزامن عمداً (CPU خفيف). استدعِه عبر asyncio.to_thread من البوت."""

    def build_workbook(
        self, 
        project_idea: str, 
        location: str, 
        capital_text: str,
        overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Tuple[Workbook, List[Assumption], List[str], str]:
        capex_usd, capex_note = parse_capital(capital_text)
        warnings: List[str] = []
        if capex_usd is None:
            warnings.append(f"رأس المال غير محدد ({capex_note}) — استُخدم افتراض 500,000 دولار بثقة Low.")
        items = default_assumptions(capex_usd, capex_note, overrides)
        wb = Workbook()
        _sheet_assumptions(wb, items, project_idea)
        _sheet_model(wb)
        _sheet_checks(wb)
        _sheet_summary(wb, project_idea, location, capex_note)
        sens = _sheet_sensitivity(wb, items)
        wb._castlix_sens = sens  # type: ignore[attr-defined]
        wb.move_sheet("Sensitivity", offset=-(len(wb.sheetnames) - 3))  # الترتيب: Summary, Assumptions, Sensitivity, Model, Checks
        wb.active = 0
        return wb, items, warnings, capex_note

    def generate_financial_model(
        self, 
        project_idea: str, 
        location: str, 
        capital_text: str,
        market_data: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        tracker=None
    ) -> FinanceResult:
        logger.info("بناء النموذج المالي لـ: %s", project_idea)
        wb, items, warnings, _ = self.build_workbook(project_idea, location, capital_text, overrides)
        buf = io.BytesIO()
        wb.save(buf)
        base = run_model(params_for(items, "base"))["metrics"]
        undocumented = sum(1 for a in items if a.confidence == "Low")
        if undocumented:
            warnings.append(f"{undocumented} من {len(items)} فرضية غير موثقة (Low) — النتائج أولية فقط.")
        sens = wb._castlix_sens  # type: ignore[attr-defined]
        return FinanceResult(
            file_bytes=buf.getvalue(), 
            metrics=base, 
            scenarios=sens["scenarios"],
            undocumented=undocumented, 
            total_assumptions=len(items), 
            warnings=warnings,
            capital_usd=base["capex"],
        )
