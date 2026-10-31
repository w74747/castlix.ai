"""
finance_core.py — النواة الحسابية للنموذج المالي (نسخة بايثون مطابقة لمنطق ملف الإكسيل).

الغرض:
  1) حساب جداول الحساسية والسيناريوهات التي تُكتب كقيم في ورقة Sensitivity.
  2) تغذية العرض التقديمي وملخص تليجرام بأرقام حقيقية بدلاً من أرقام مختلقة.
  3) الاختبار: تتم مقارنة نتائج هذه النواة بنتائج الإكسيل بعد إعادة حسابه (tests/).

أي تعديل على منطق الصيغ في finance.py يجب أن يُعكس هنا، واختبار التطابق سيكشف أي اختلاف.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional

HORIZON = 5  # عدد سنوات التشغيل الصريحة (السنة 0 = الاستثمار)


@dataclass(frozen=True)
class Params:
    """القيم الفعّالة لسيناريو واحد (ما يظهر في عمود Active في سجل الفرضيات)."""
    capex: float          # إجمالي النفقات الرأسمالية (دولار) — تُصرف في السنة 0
    capacity: float       # الطاقة الإنتاجية السنوية (وحدات)
    util_y1: float        # نسبة استغلال الطاقة في السنة 1
    util_step: float      # الزيادة السنوية في الاستغلال (نقاط مئوية)
    util_max: float       # سقف الاستغلال
    price: float          # سعر بيع الوحدة في السنة 1
    price_growth: float   # نمو السعر السنوي
    var_cost: float       # التكلفة المتغيرة للوحدة في السنة 1
    fixed_opex: float     # المصروفات الثابتة السنوية في السنة 1
    inflation: float      # تضخم التكاليف
    wacc: float           # معدل الخصم
    debt_share: float     # نسبة التمويل بالدين من CapEx
    interest: float       # سعر الفائدة
    tenor: int            # مدة السداد (سنوات) — أقساط أصل متساوية
    tax: float            # معدل ضريبة الدخل
    dep_life: int         # العمر الإنتاجي للإهلاك (قسط ثابت)
    nwc_pct: float        # رأس المال العامل كنسبة من الإيراد
    terminal_g: float     # نمو القيمة النهائية (Gordon)


def irr(cashflows: List[float], lo: float = -0.95, hi: float = 10.0) -> Optional[float]:
    """معدل العائد الداخلي بالتنصيف. يعيد None إن لم يوجد تغيّر إشارة."""
    def f(r: float) -> float:
        return sum(cf / (1.0 + r) ** t for t, cf in enumerate(cashflows))

    f_lo, f_hi = f(lo), f(hi)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if abs(f_mid) < 1e-9:
            return mid
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def run_model(p: Params) -> Dict:
    """ينفّذ النموذج ويعيد السلاسل الزمنية (فهرس 0..5) والمؤشرات."""
    n = HORIZON
    z = lambda: [0.0] * (n + 1)  # noqa: E731

    util, vol, price, rev, vcu, varc, fixed = z(), z(), z(), z(), z(), z(), z()
    ebitda, dep, ebit = z(), z(), z()
    d_open, repay, d_close, interest = z(), z(), z(), z()
    ebt, tax, ni = z(), z(), z()
    nwc, dnwc, capex, utax = z(), z(), z(), z()
    fcf, tv, fcf_tv = z(), z(), z()
    cfads, ds, eq = z(), z(), z()
    dscr: List[Optional[float]] = [None] * (n + 1)

    debt0 = p.capex * p.debt_share
    d_close[0] = debt0
    capex[0] = p.capex
    fcf[0] = -p.capex
    eq[0] = -p.capex + debt0

    for t in range(1, n + 1):
        util[t] = min(p.util_max, p.util_y1 + (t - 1) * p.util_step)
        vol[t] = p.capacity * util[t]
        price[t] = p.price * (1 + p.price_growth) ** (t - 1)
        rev[t] = vol[t] * price[t]
        vcu[t] = p.var_cost * (1 + p.inflation) ** (t - 1)
        varc[t] = vol[t] * vcu[t]
        fixed[t] = p.fixed_opex * (1 + p.inflation) ** (t - 1)
        ebitda[t] = rev[t] - varc[t] - fixed[t]
        dep[t] = p.capex / p.dep_life if t <= p.dep_life else 0.0
        ebit[t] = ebitda[t] - dep[t]

        d_open[t] = d_close[t - 1]
        repay[t] = min(d_open[t], debt0 / p.tenor) if t <= p.tenor else 0.0
        d_close[t] = d_open[t] - repay[t]
        interest[t] = d_open[t] * p.interest

        ebt[t] = ebit[t] - interest[t]
        tax[t] = max(0.0, ebt[t]) * p.tax
        ni[t] = ebt[t] - tax[t]

        nwc[t] = rev[t] * p.nwc_pct
        dnwc[t] = nwc[t] - nwc[t - 1]
        utax[t] = max(0.0, ebit[t]) * p.tax
        fcf[t] = ebitda[t] - utax[t] - dnwc[t]

        cfads[t] = ebitda[t] - tax[t] - dnwc[t]
        ds[t] = interest[t] + repay[t]
        dscr[t] = (cfads[t] / ds[t]) if ds[t] != 0 else None
        eq[t] = cfads[t] - interest[t] - repay[t]

    tv[n] = fcf[n] * (1 + p.terminal_g) / (p.wacc - p.terminal_g) if p.wacc > p.terminal_g else 0.0
    for t in range(n + 1):
        fcf_tv[t] = fcf[t] + tv[t]

    df = [1.0 / (1 + p.wacc) ** t for t in range(n + 1)]
    npv_explicit = sum(fcf[t] * df[t] for t in range(n + 1))
    npv_tv = npv_explicit + sum(tv[t] * df[t] for t in range(n + 1))

    # فترة الاسترداد (على التدفق بدون قيمة نهائية) مع استيفاء خطي داخل السنة
    cum = [fcf[0]]
    for t in range(1, n + 1):
        cum.append(cum[-1] + fcf[t])
    payback: Optional[float] = None
    for t in range(1, n + 1):
        if cum[t - 1] < 0 <= cum[t]:
            payback = (t - 1) + (-cum[t - 1]) / fcf[t]
            break

    dscr_vals = [d for d in dscr[1:] if d is not None]
    margin_y3 = ebitda[3] / rev[3] if rev[3] else 0.0
    be_units = (p.fixed_opex / (p.price - p.var_cost)) if p.price > p.var_cost else None
    be_util = (be_units / p.capacity) if (be_units is not None and p.capacity) else None

    return {
        "series": {
            "util": util, "vol": vol, "price": price, "rev": rev, "varc": varc, "fixed": fixed,
            "ebitda": ebitda, "dep": dep, "ebit": ebit, "interest": interest, "repay": repay,
            "d_close": d_close, "tax": tax, "ni": ni, "fcf": fcf, "tv": tv, "cfads": cfads,
            "ds": ds, "dscr": dscr, "eq": eq, "cum": cum,
        },
        "metrics": {
            "npv_explicit": npv_explicit,
            "npv_tv": npv_tv,
            "irr_explicit": irr(fcf),
            "irr_tv": irr(fcf_tv),
            "irr_equity": irr(eq),
            "payback": payback,  # None => أكثر من 5 سنوات
            "min_dscr": min(dscr_vals) if dscr_vals else None,
            "avg_dscr": (sum(dscr_vals) / len(dscr_vals)) if dscr_vals else None,
            "ebitda_margin_y3": margin_y3,
            "revenue_y1": rev[1],
            "revenue_y5": rev[5],
            "ebitda_y5": ebitda[5],
            "capex": p.capex,
            "break_even_util": be_util,
        },
    }


# ---------------------------------------------------------------------------
# الحساسية والسيناريوهات (تُكتب كقيم ثابتة في ورقة Sensitivity)
# ---------------------------------------------------------------------------
def scale(p: Params, *, price: float = 1.0, volume: float = 1.0, var_cost: float = 1.0,
          fixed: float = 1.0, capex: float = 1.0, wacc_shift: float = 0.0) -> Params:
    return replace(
        p,
        price=p.price * price,
        capacity=p.capacity * volume,
        var_cost=p.var_cost * var_cost,
        fixed_opex=p.fixed_opex * fixed,
        capex=p.capex * capex,
        wacc=p.wacc + wacc_shift,
    )


def grid_price_volume(p: Params, steps=(-0.2, -0.1, 0.0, 0.1, 0.2)) -> Dict:
    """شبكة NPV (شاملة القيمة النهائية): السعر (صفوف) × الحجم (أعمدة)."""
    rows = []
    for ps in steps:
        row = []
        for vs in steps:
            m = run_model(scale(p, price=1 + ps, volume=1 + vs))["metrics"]
            row.append(m["npv_tv"])
        rows.append(row)
    return {"steps": list(steps), "values": rows}


def tornado(p: Params, delta: float = 0.10) -> List[Dict]:
    """أثر تغيير ±delta في كل متغير على NPV (شاملة القيمة النهائية)، مرتبة تنازلياً بالأثر."""
    base = run_model(p)["metrics"]["npv_tv"]
    cases = [
        ("سعر البيع", dict(price=1 - delta), dict(price=1 + delta)),
        ("حجم المبيعات", dict(volume=1 - delta), dict(volume=1 + delta)),
        ("التكلفة المتغيرة", dict(var_cost=1 + delta), dict(var_cost=1 - delta)),
        ("المصروفات الثابتة", dict(fixed=1 + delta), dict(fixed=1 - delta)),
        ("النفقات الرأسمالية", dict(capex=1 + delta), dict(capex=1 - delta)),
        ("معدل الخصم (±1 نقطة)", dict(wacc_shift=+0.01), dict(wacc_shift=-0.01)),
    ]
    out = []
    for label, bad, good in cases:
        lo = run_model(scale(p, **bad))["metrics"]["npv_tv"]
        hi = run_model(scale(p, **good))["metrics"]["npv_tv"]
        out.append({"label": label, "low": lo, "high": hi, "base": base, "swing": abs(hi - lo)})
    out.sort(key=lambda r: r["swing"], reverse=True)
    return out
