"""債務動態與長端供給壓力。

核心問題：長端利率為什麼在這裡、誰在發債、買盤吃不吃得下。
利息負擔用「利息支出 ÷ 稅收」而非只看佔 GDP，因為前者才是實際的排擠。
債務動態用 r−g 框架：實質利率高於實質成長時，債務佔 GDP 自動上升。
"""
from __future__ import annotations

from ..data import Bundle


def debt_dynamics(bundle: Bundle) -> dict:
    """r − g：債務佔 GDP 會不會自己滾大。"""
    debt_gdp = bundle["GFDEGDQ188S"]
    real10 = bundle["DFII10"]
    gdp = bundle["GDPC1"]

    real_rate = real10.last
    real_growth = None
    if gdp and len(gdp) >= 5:
        real_growth = gdp.yoy().last

    r_minus_g = None
    if real_rate is not None and real_growth is not None:
        r_minus_g = real_rate - real_growth

    # 穩定債務比所需的基本盈餘 ≈ (r-g)/(1+g) × 債務比
    required_primary = None
    if r_minus_g is not None and debt_gdp.last is not None and real_growth is not None:
        required_primary = (r_minus_g / 100) / (1 + real_growth / 100) * debt_gdp.last

    return {
        "debt_gdp": debt_gdp.last,
        "debt_gdp_series": debt_gdp,
        "debt_gdp_5y_ago": debt_gdp.at(-21),
        "real_rate": real_rate,
        "real_growth": real_growth,
        "r_minus_g": r_minus_g,
        "required_primary": required_primary,
        "verdict": ("實質利率高於實質成長，債務佔 GDP 會自動累積"
                    if r_minus_g is not None and r_minus_g > 0
                    else "實質成長高於實質利率，債務比可自然稀釋"
                    if r_minus_g is not None else "資料不足"),
    }


def fiscal(bundle: Bundle) -> dict:
    """赤字、利息負擔與月度收支。"""
    deficit_gdp = bundle["FYFSGDA188S"]
    interest = bundle["A091RC1Q027SBEA"]
    interest_gdp = bundle["FYOIGDA188S"]
    monthly = bundle["MTSDS133FMS"]

    # 滾動 12 個月赤字（月度收支為當月餘額，百萬美元）
    rolling = monthly.rolling_sum(12) if len(monthly) >= 12 else None
    annual_deficit = rolling.last if rolling else None

    return {
        "deficit_gdp": deficit_gdp.last,
        "deficit_gdp_series": deficit_gdp,
        "interest": interest.last,
        "interest_series": interest,
        "interest_gdp": interest_gdp.last,
        "interest_yoy": interest.yoy().last if interest else None,
        "annual_deficit": annual_deficit,
        "rolling_series": rolling,
        "monthly_series": monthly,
    }


MILLIONS_PER_TRILLION = 1_000_000
BILLIONS_PER_TRILLION = 1_000


def _at(series, when):
    """某一季的值；那一季沒有就是 None。佔比的分子分母一定要同一季——
    兩檔序列的最新一季常常不同（外國持有比債務總額晚一季公布）。"""
    for d, v in zip(reversed(series.dates), reversed(series.values)):
        if d == when:
            return v
        if d < when:
            return None
    return None


def holders(bundle: Bundle) -> dict:
    """誰持有這些債。金額一律換成「兆美元」再交出去。

    三檔序列的單位不一樣（GFDEBTN 是百萬美元，FDHBFIN／FDHBPIN 是十億美元），
    最新一季也不一樣。2026-10-10 以前這裡把三檔都當百萬美元、而且拿各自的最新一季
    相除——外國持有 9.355 兆被印成 0.01 兆、佔比 0.0%。

    三個數字不是互斥的分類：債務總額＝公眾持有＋政府內部持有（社安基金等）；
    民間持有＝公眾持有扣掉聯準會；外國持有是民間持有的一部分。所以不能相加，
    也不能拿「外國＋民間」去對總額。
    """
    foreign, private, total = bundle["FDHBFIN"], bundle["FDHBPIN"], bundle["GFDEBTN"]

    def trillions(value, per):
        return None if value is None else value / per

    def share(when):
        """外國持有佔債務總額，同一季才算。"""
        f, t = _at(foreign, when), _at(total, when)
        if f is None or not t:
            return None
        return (f / BILLIONS_PER_TRILLION) / (t / MILLIONS_PER_TRILLION) * 100

    # 分子分母都有的最新一季
    common = next((d for d in reversed(foreign.dates) if _at(total, d)), None)
    five_years_ago = common.replace(year=common.year - 5) if common else None
    return {
        "total": trillions(total.last, MILLIONS_PER_TRILLION), "total_as_of": total.last_date,
        "foreign": trillions(foreign.last, BILLIONS_PER_TRILLION), "foreign_as_of": foreign.last_date,
        "private": trillions(private.last, BILLIONS_PER_TRILLION), "private_as_of": private.last_date,
        "foreign_share": share(common) if common else None,
        "foreign_share_as_of": common,
        "foreign_share_5y_ago": share(five_years_ago) if five_years_ago else None,
        "foreign_series": foreign,
        "foreign_yoy": foreign.yoy().last if foreign else None,
    }


def supply_pressure(bundle: Bundle, dynamics: dict, fiscal_data: dict) -> dict:
    """把幾個供給端訊號合成一個偏多／偏少的判斷。"""
    score = 0
    reasons = []

    if dynamics.get("r_minus_g") is not None and dynamics["r_minus_g"] > 0:
        score += 1
        reasons.append(f"r−g 為 {dynamics['r_minus_g']:+.1f} 個百分點，債務自動累積")
    if fiscal_data.get("deficit_gdp") is not None and abs(fiscal_data["deficit_gdp"]) > 4:
        score += 1
        reasons.append(f"赤字佔 GDP {abs(fiscal_data['deficit_gdp']):.1f}%，處於承平時期高位")
    if fiscal_data.get("interest_yoy") is not None and fiscal_data["interest_yoy"] > 8:
        score += 1
        reasons.append(f"利息支出年增 {fiscal_data['interest_yoy']:+.0f}%")
    if dynamics.get("debt_gdp") is not None and dynamics["debt_gdp"] > 110:
        score += 1
        reasons.append(f"聯邦債務佔 GDP {dynamics['debt_gdp']:.0f}%")

    level = "高" if score >= 3 else "中" if score == 2 else "低"
    return {"score": score, "level": level, "reasons": reasons, "max": 4}


def health_checks(bundle: Bundle, dynamics: dict, fiscal_data: dict,
                  holders_data: dict) -> list[dict]:
    checks = []

    def add(name, state, reading, note=""):
        checks.append({"name": name, "state": state, "reading": reading, "note": note})

    if dynamics.get("debt_gdp") is not None:
        value = dynamics["debt_gdp"]
        state = "alert" if value > 120 else "watch" if value > 100 else "normal"
        add("聯邦債務佔 GDP", state, f"{value:.0f}%",
            "高於二戰後高點" if value > 120 else "")

    if dynamics.get("r_minus_g") is not None:
        value = dynamics["r_minus_g"]
        state = "alert" if value > 1.0 else "watch" if value > 0 else "normal"
        add("r − g", state, f"{value:+.1f} 個百分點", dynamics["verdict"])

    if fiscal_data.get("deficit_gdp") is not None:
        value = abs(fiscal_data["deficit_gdp"])
        state = "alert" if value > 6 else "watch" if value > 4 else "normal"
        add("財政赤字佔 GDP", state, f"{value:.1f}%",
            "承平時期少見的赤字規模" if value > 5 else "")

    if fiscal_data.get("interest_gdp") is not None:
        value = fiscal_data["interest_gdp"]
        state = "alert" if value > 3.5 else "watch" if value > 2.5 else "normal"
        add("利息支出佔 GDP", state, f"{value:.1f}%",
            "利息開始排擠其他支出" if value > 2.5 else "")

    if fiscal_data.get("interest_yoy") is not None:
        value = fiscal_data["interest_yoy"]
        state = "alert" if value > 15 else "watch" if value > 8 else "normal"
        add("利息支出年增", state, f"{value:+.0f}%",
            "舊債換新債的成本上升中" if value > 8 else "")

    if holders_data.get("foreign_share") is not None:
        value = holders_data["foreign_share"]
        prior = holders_data.get("foreign_share_5y_ago")
        state = "watch" if prior and value < prior - 3 else "normal"
        add("外國持有佔比", state, f"{value:.0f}%",
            f"五年前為 {prior:.0f}%，外資佔比下降代表本國買盤要吃更多" if prior else "")

    return checks


def compute(bundle: Bundle) -> dict:
    dynamics = debt_dynamics(bundle)
    fiscal_data = fiscal(bundle)
    holders_data = holders(bundle)
    return {
        "as_of": bundle["GFDEGDQ188S"].last_date,
        "dynamics": dynamics,
        "fiscal": fiscal_data,
        "holders": holders_data,
        "supply": supply_pressure(bundle, dynamics, fiscal_data),
        "checks": health_checks(bundle, dynamics, fiscal_data, holders_data),
    }
