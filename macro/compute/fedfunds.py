"""期貨隱含的升降息機率——CME FedWatch 的同一套算法，自己算。

原理只有一條：30 天聯邦基金期貨的價格 = 100 − 該合約月的平均 EFFR。
會議落在月中時，當月平均是「會前利率 × 會前天數 + 會後利率 × 會後天數」
的加權；會前利率已知（今天的 EFFR，或上一場會議反推出的會後利率），
反解就得到市場對會後利率的預期。會後減會前，除以 25 bp，就是「動一碼」
的機率——FedWatch 同樣假設每次會議只在相鄰兩個 25 bp 檔位之間分配機率。

會議落在月底（10/28、1/27 這種）時，當月合約幾乎全是會前天數，反解會把
雜訊放大幾十倍；FedWatch 的做法是改用下個月（沒有會議）的合約，它的
月平均就是會後利率本身。這裡照做。
"""
from __future__ import annotations

import calendar
from datetime import date

from .. import fomc
from ..data import Bundle
from ..sources import fedfunds as source

STEP_BP = 25
MIN_POST_DAYS = 10       # 會後天數少於這個，就改用下月合約
HORIZON_MONTHS = 12


def implied_rates(prices: dict[str, float]) -> dict[str, float]:
    return {ym: round(100.0 - p, 4) for ym, p in prices.items() if p is not None}


def _next_month(ym: str) -> str:
    year, month = int(ym[:4]), int(ym[5:7])
    month += 1
    if month > 12:
        month, year = 1, year + 1
    return f"{year}-{month:02d}"


def split_probability(change_bp: float) -> dict[str, float]:
    """把預期變動拆成相鄰兩個檔位的機率。

    +15 bp → 一碼 60%、不變 40%；−37.5 bp → 一碼 50%、兩碼 50%。
    超過兩碼的都歸入 50 那格——遠月合約本來就只能當方向看。
    """
    probs = {"hike50": 0.0, "hike25": 0.0, "hold": 0.0, "cut25": 0.0, "cut50": 0.0}
    side = "hike" if change_bp > 0 else "cut"
    steps = abs(change_bp) / STEP_BP
    whole = int(steps)
    frac = steps - whole

    def put(n: int, p: float) -> None:
        if p <= 0:
            return
        key = "hold" if n == 0 else f"{side}25" if n == 1 else f"{side}50"
        probs[key] += p

    put(whole, 1 - frac)
    put(whole + 1, frac)
    return {k: round(v, 4) for k, v in probs.items()}


def implied_path(prices: dict[str, float], effr: float,
                 meetings: list[date], today: date) -> list[dict]:
    """逐場會議反推會後利率與機率。合約不夠就停在那裡，不外插。"""
    implied = implied_rates(prices)
    r_before = effr
    rows = []
    for when in meetings:
        if when < today:
            continue
        ym = f"{when.year}-{when.month:02d}"
        days_in_month = calendar.monthrange(when.year, when.month)[1]
        # 決策日當天仍是舊利率，新利率隔天生效
        post_days = days_in_month - when.day
        if post_days >= MIN_POST_DAYS:
            if ym not in implied:
                break
            r_after = (implied[ym] * days_in_month - r_before * when.day) / post_days
            basis = ym
        else:
            basis = _next_month(ym)
            if basis not in implied:
                break
            r_after = implied[basis]
        change_bp = (r_after - r_before) * 100
        probs = split_probability(change_bp)
        p_hike = probs["hike25"] + probs["hike50"]
        p_cut = probs["cut25"] + probs["cut50"]
        rows.append({
            "date": when, "label": f"{when.month}/{when.day}",
            "before": round(r_before, 4), "after": round(r_after, 4),
            "change_bp": round(change_bp, 1),
            "cumulative_bp": round((r_after - effr) * 100, 1),
            "probs": probs,
            "p_hike": round(p_hike, 4), "p_hold": probs["hold"], "p_cut": round(p_cut, 4),
            "headline": (f"升息機率 {p_hike:.0%}" if p_hike >= p_cut
                         else f"降息機率 {p_cut:.0%}"),
            "basis": basis,
        })
        r_before = r_after
    return rows


def summarise(rows: list[dict]) -> str:
    if not rows:
        return ""
    last = rows[-1]
    cum = last["cumulative_bp"]
    label = f"{last['date'].year}/{last['date'].month}"
    if abs(cum) < STEP_BP / 2:
        return f"期貨定價到 {label} 政策利率大致不動（累計 {cum:+.0f} bp）"
    word = "升息" if cum > 0 else "降息"
    return f"期貨定價到 {label} 累計{word} {abs(cum):.0f} bp（約 {abs(cum) / STEP_BP:.1f} 碼）"


def compute(bundle: Bundle) -> dict:
    effr = bundle["DFF"].last
    today = date.today()
    if effr is None:
        return {"available": False, "reason": "沒有有效聯邦資金利率（DFF）可當起點",
                "rows": [], "monthly": []}

    months = source.contract_months(today, HORIZON_MONTHS)
    found = source.fetch([symbol for _, symbol in months])
    monthly = []
    for ym, symbol in months:
        row = found.get(symbol)
        if not row:
            continue
        monthly.append({"ym": ym, "symbol": symbol, "price": row["price"],
                        "implied": round(100.0 - row["price"], 3),
                        "stale": row["stale"], "quoted_at": row.get("quoted_at"),
                        "source": row.get("source")})
    prices = {m["ym"]: m["price"] for m in monthly}
    rows = implied_path(prices, effr, fomc.MEETINGS, today)
    if not rows:
        return {"available": False,
                "reason": ("這一輪拿不到聯邦基金期貨報價" if not monthly
                           else "行事曆上的下次會議沒有對應的合約"),
                "rows": [], "monthly": monthly, "effr": effr}

    return {
        "available": True,
        "effr": effr,
        "effr_date": bundle["DFF"].last_date,
        "rows": rows,
        "monthly": monthly,
        "stale": all(m["stale"] for m in monthly),
        "quoted_at": max((m["quoted_at"] for m in monthly if m["quoted_at"]), default=None),
        "summary": summarise(rows),
        "next": rows[0],
    }
