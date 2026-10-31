"""اختبارات النموذج المالي: تحليل رأس المال، تطابق الإكسيل مع النسخة البايثونية، تبديل السيناريوهات.
اختبارات الإكسيل تحتاج LibreOffice: اضبط RECALC_CMD مثل:  RECALC_CMD="python /path/to/recalc.py"
"""
import io
import os
import shlex
import subprocess
import tempfile

import pytest
from openpyxl import load_workbook

from agents.finance import FinancialModelingAgent, ORDER, default_assumptions, params_for, parse_capital
from agents.finance_core import irr, run_model

RECALC = os.getenv("RECALC_CMD")


@pytest.mark.parametrize("text,expected", [
    ("2 مليون دولار", 2_000_000), 
    ("500,000", 500_000), 
    ("٥٠٠٬٠٠٠", 500_000), 
    ("1.5M", 1_500_000),
    ("300 ألف ريال عماني", 300_000 * 2.6008), 
    ("ابحث أنت", None), 
    ("abc", None), 
    ("", None),
])
def test_parse_capital(text, expected):
    val, _ = parse_capital(text)
    assert (val is None) if expected is None else abs(val - expected) < 1


def test_irr_known_value():
    assert abs(irr([-100, 110]) - 0.10) < 1e-9
    assert irr([100, 100]) is None  # لا تغيّر إشارة


def test_defaults_honest_labels():
    items = default_assumptions(None, "x")
    assert len(items) == len(ORDER)
    assert all(a.confidence == "Low" for a in items)  # لا ثقة مرتفعة بلا مصدر حقيقي
    assert not any("Sec-Edgar" in a.source or "FMP" in a.source for a in items)  # منع المصادر الوهمية
    user = default_assumptions(1_000_000, "مدخل المستخدم")
    assert next(a for a in user if a.key == "capex").confidence == "Medium"


def test_scenarios_are_ordered():
    items = default_assumptions(1_000_000, "u")
    npv = {s: run_model(params_for(items, s))["metrics"]["npv_tv"] for s in ("down", "base", "up")}
    assert npv["down"] < npv["base"] < npv["up"]


def _recalc(path):
    out = subprocess.run(shlex.split(RECALC) + [path, "120"], capture_output=True, text=True, timeout=180)
    assert '"status": "success"' in out.stdout, out.stdout + out.stderr
    assert '"total_errors": 0' in out.stdout, out.stdout


@pytest.mark.skipif(not RECALC, reason="RECALC_CMD غير مضبوط (يتطلب LibreOffice)")
@pytest.mark.parametrize("scenario,key", [("Base", "base"), ("Downside", "down"), ("Upside", "up")])
def test_excel_matches_python(scenario, key):
    agent = FinancialModelingAgent()
    wb, items, _, _ = agent.build_workbook("مصنع", "صحار", "2 مليون دولار")
    wb["Assumptions"]["C3"] = scenario
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "m.xlsx")
        wb.save(path)
        _recalc(path)
        S = load_workbook(path, data_only=True)["Summary"]
        C = load_workbook(path, data_only=True)["Checks"]
        m = run_model(params_for(items, key))["metrics"]
        pairs = {
            5: "npv_explicit", 
            6: "npv_tv", 
            7: "irr_explicit", 
            8: "irr_tv", 
            9: "irr_equity",
            10: "payback", 
            11: "min_dscr", 
            12: "avg_dscr", 
            13: "ebitda_margin_y3", 
            15: "break_even_util"
        }
        for row, k in pairs.items():
            xl, py = S[f"B{row}"].value, m[k]
            if isinstance(xl, (int, float)) and py is not None:
                assert abs(xl - py) <= max(1e-6, 1e-6 * abs(py)), (scenario, k, xl, py)
        assert S["B18"].value == "ALL OK"
        assert S["B20"].value == sum(1 for a in items if a.confidence == "Low")
