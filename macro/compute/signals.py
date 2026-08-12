"""訊號規則引擎。

每條規則是一個純函式：吃各模組的計算結果，回傳 None 或一個訊號 dict。
門檻全部寫死在規則裡，不隨資料自適應 — 同一份資料每次執行結果一致，
也才能拿去跟上期比對。

訊號欄位：
  key        穩定識別碼，用於與上期做 diff
  headline   一句話結論
  why        為什麼這件事重要
  evidence   支撐的數字
  direction  hawkish（利升息）/ dovish（利降息）/ neutral
  severity   high / medium / low
  module     來源模組
"""
from __future__ import annotations

from typing import Callable

RULES: list[Callable] = []


def rule(fn):
    RULES.append(fn)
    return fn


def _signal(key, headline, why, evidence, direction, severity, module):
    return {"key": key, "headline": headline, "why": why, "evidence": evidence,
            "direction": direction, "severity": severity, "module": module}


# ============================================================ 就業規則 =======

@rule
def payrolls_below_breakeven(ctx):
    labor = ctx["labor"]
    avg3 = labor["payrolls"]["avg3"]
    breakeven = labor["breakeven"].get("value")
    if avg3 is None or breakeven is None or avg3 >= breakeven:
        return None
    severity = "high" if avg3 < breakeven * 0.5 else "medium"
    return _signal(
        "payrolls_below_breakeven",
        "三月均非農低於損益兩平，撐不住現有失業率",
        "就業增速低於勞動力成長時，失業率會自己往上飄，不需要裁員潮",
        f"三月均 {avg3 / 10:+.1f} 萬人，損益兩平約 {breakeven / 10:.1f} 萬人",
        "dovish", severity, "就業")


@rule
def systematic_downward_revisions(ctx):
    revisions = ctx["labor"]["revisions"]
    share = revisions.get("negative_share")
    avg = revisions.get("avg")
    if share is None or avg is None or share < 0.6 or avg >= 0:
        return None
    severity = "high" if share >= 0.75 and avg < -20 else "medium"
    return _signal(
        "systematic_downward_revisions",
        "初值近一年呈系統性下修，實質動能弱於初值",
        "初值持續高估時，當月公布的數字應該打折看待",
        f"近 {revisions['n']} 個月有 {share * 100:.0f}% 遭下修，平均修正 {avg / 10:+.1f} 萬人",
        "dovish", severity, "就業")


@rule
def unemployment_off_lows(ctx):
    gap = ctx["labor"]["unemployment"].get("gap_from_low")
    if gap is None or gap < 0.3:
        return None
    severity = "high" if gap >= 0.5 else "medium"
    return _signal(
        "unemployment_off_lows",
        "失業率明顯離開一年低點",
        "Sahm 法則以三月均失業率高出一年低點 0.5 個百分點為衰退訊號",
        f"距一年低點 +{gap:.1f} 個百分點",
        "dovish", severity, "就業")


@rule
def narrow_job_growth(ctx):
    sectors = ctx["labor"]["sectors"]
    diffusion = sectors.get("diffusion")
    if diffusion is None or diffusion > 45:
        return None
    return _signal(
        "narrow_job_growth",
        "就業成長集中在少數行業，擴散度偏低",
        "擴散度低代表成長不是全面性的，一旦領頭行業轉弱就沒有替補",
        f"{sectors['n']} 個行業中僅 {diffusion:.0f}% 增加就業",
        "dovish", "medium", "就業")


@rule
def unemployment_falling_for_wrong_reason(ctx):
    """失業率下降，但分母（勞動力）在萎縮 — 這不是改善。"""
    labor = ctx["labor"]
    participation = labor["participation"]
    population_growth = participation.get("population_growth")
    labor_force_growth = participation.get("labor_force_growth")
    prime_change = participation.get("prime_epop_change")
    rows = (labor.get("decomposition") or {}).get("rows") or []
    year = next((r for r in rows if r["window"] == "一年"), None)

    if (population_growth is None or labor_force_growth is None
            or labor_force_growth >= 0 or population_growth <= 0):
        return None
    # 失業率持平或下降時才成立；若失業率已在上升，那是另一條規則的事。
    if year is None or year["total"] > 0.1:
        return None

    evidence = (f"人口月增 {population_growth / 10:+.1f} 萬、勞動力月增 "
                f"{labor_force_growth / 10:+.1f} 萬")
    if prime_change is not None:
        evidence += f"；黃金年齡就業率 12 個月 {prime_change:+.1f} 個百分點"

    return _signal(
        "unemployment_falling_for_wrong_reason",
        "失業率下降來自勞動力萎縮，不是就業改善",
        "人口在增加而勞動力在減少，代表失業率是被「退出勞動力」壓下去的；"
        "這種下降不代表勞動市場變好，也不該被讀成升息的理由",
        evidence,
        "dovish", "high", "就業")


@rule
def labor_market_tight(ctx):
    jolts = ctx["labor"]["jolts"]
    ratio = jolts.get("vu_ratio")
    wages = ctx["labor"]["wages"].get("yoy")
    if ratio is None or ratio < 1.2 or wages is None or wages < 4.0:
        return None
    return _signal(
        "labor_market_tight",
        "職缺仍遠多於求職者，且薪資增速偏高",
        "勞動市場過緊會透過服務業成本持續推升通膨",
        f"職缺對失業比 {ratio:.2f}，時薪年增 {wages:.1f}%",
        "hawkish", "medium", "就業")


@rule
def claims_rising(ctx):
    claims = ctx["labor"]["claims"]
    series = claims.get("ma_series")
    if not series or len(series) < 60:
        return None
    low = min(series.last_years(1).values)
    if not low or series.last is None:
        return None
    ratio = series.last / low
    if ratio < 1.15:
        return None
    severity = "high" if ratio > 1.25 else "medium"
    return _signal(
        "claims_rising",
        "初領失業金四週均明顯高於一年低點",
        "初領件數是最即時的裁員訊號，領先失業率數月",
        f"{series.last / 10000:.1f} 萬人，較一年低點高 {(ratio - 1) * 100:.0f}%",
        "dovish", severity, "就業")


@rule
def quits_collapsed(ctx):
    quits = ctx["labor"]["jolts"].get("quits")
    if quits is None or quits > 2.0:
        return None
    return _signal(
        "quits_collapsed",
        "主動離職率降到低檔，勞工議價力下降",
        "離職率是薪資增速的領先指標，走低意味未來薪資壓力降溫",
        f"主動離職率 {quits:.1f}%",
        "dovish", "medium", "就業")


# ============================================================ 物價規則 =======

@rule
def core_pce_above_target(ctx):
    core_pce = ctx["inflation"]["headline"].get("core_pce")
    target = ctx["inflation"]["target"]
    if core_pce is None or core_pce <= target + 0.3:
        return None
    gap = core_pce - target
    severity = "high" if gap > 1.0 else "medium"
    return _signal(
        "core_pce_above_target",
        "核心 PCE 顯著高於目標",
        "核心 PCE 是聯準會的政策標的，未回到目標前降息的門檻就高",
        f"核心 PCE {core_pce:.1f}%，距 2% 目標 {gap:+.1f} 個百分點",
        "hawkish", severity, "物價")


@rule
def momentum_cooling(ctx):
    momentum = ctx["inflation"]["momentum"]
    headline = ctx["inflation"]["headline"]
    ann3 = momentum.get("core_cpi_3m")
    yoy = headline.get("core_cpi")
    if ann3 is None or yoy is None:
        return None
    diff = ann3 - yoy
    if diff > -0.4:
        return None
    severity = "medium" if diff > -0.8 else "high"
    return _signal(
        "momentum_cooling",
        "核心 CPI 近三月年化明顯低於年增率",
        "近月動能領先年增率，是通膨降溫最早的證據",
        f"近三月年化 {ann3:.1f}%，年增 {yoy:.1f}%，低 {abs(diff):.1f} 個百分點",
        "dovish", severity, "物價")


@rule
def momentum_reaccelerating(ctx):
    momentum = ctx["inflation"]["momentum"]
    headline = ctx["inflation"]["headline"]
    ann3 = momentum.get("core_cpi_3m")
    yoy = headline.get("core_cpi")
    if ann3 is None or yoy is None or ann3 - yoy < 0.4:
        return None
    return _signal(
        "momentum_reaccelerating",
        "核心 CPI 近三月年化高於年增率，通膨在再加速",
        "近月動能轉強會先於年增率反彈出現",
        f"近三月年化 {ann3:.1f}%，年增 {yoy:.1f}%",
        "hawkish", "high", "物價")


@rule
def supercore_sticky(ctx):
    supercore = ctx["inflation"]["supercore"]
    yoy = supercore.get("yoy")
    months = supercore.get("months_above", 0)
    if yoy is None or yoy < 2.5 or months < 6:
        return None
    severity = "high" if yoy > 3.5 else "medium"
    return _signal(
        "supercore_sticky",
        "核心服務除住房卡在目標之上",
        "這一段最貼近薪資，也是聯準會最在意的黏性來源",
        f"年增 {yoy:.1f}%，已連 {months} 個月高於 2.5%",
        "hawkish", severity, "物價")


@rule
def shelter_still_dragging(ctx):
    shelter = ctx["inflation"]["shelter"]
    drag = shelter.get("drag")
    if drag is None or drag >= -0.15:
        return None
    return _signal(
        "shelter_still_dragging",
        "住房落後項仍在推升表面讀數，實際通膨比表面低",
        "住房項落後市場租金約 9 至 12 個月，收斂後會自動壓低整體讀數",
        f"住房年增 {shelter['yoy']:.1f}%、近三月年化 {shelter['ann3']:.1f}%，"
        f"收斂後對整體 CPI 約 {drag:+.2f} 個百分點",
        "dovish", "medium", "物價")


@rule
def inflation_narrow(ctx):
    breadth = ctx["inflation"]["breadth"]
    spread = breadth.get("spread")
    if spread is None or spread < 0.3:
        return None
    return _signal(
        "inflation_narrow",
        "剔除極端值後通膨明顯較低，漲勢集中",
        "集中式的漲價比全面性漲價更容易自行消退",
        f"核心 {breadth['core']:.1f}%，剔除極端值均值 {breadth['average']:.1f}%",
        "dovish", "low", "物價")


@rule
def inflation_broad(ctx):
    breadth = ctx["inflation"]["breadth"]
    spread = breadth.get("spread")
    if spread is None or spread > -0.3:
        return None
    return _signal(
        "inflation_broad",
        "剔除極端值後通膨不比核心低，漲勢是全面性的",
        "全面性的漲價需要更緊的政策才壓得下來",
        f"核心 {breadth['core']:.1f}%，剔除極端值均值 {breadth['average']:.1f}%",
        "hawkish", "medium", "物價")


@rule
def energy_upside(ctx):
    energy = ctx["inflation"]["energy"]
    wti_1m = energy.get("wti_1m")
    if wti_1m is None or wti_1m < 8:
        return None
    severity = "medium" if wti_1m < 18 else "high"
    return _signal(
        "energy_upside",
        "油價上行，未來一至兩月推升總體 CPI",
        "油價傳導到汽油約二至四週，再傳到 CPI 能源項",
        f"WTI 近一月 {wti_1m:+.1f}%，能源佔 CPI 約 {energy['weight']:.1f}%",
        "hawkish", severity, "物價")


@rule
def energy_downside(ctx):
    energy = ctx["inflation"]["energy"]
    wti_1m = energy.get("wti_1m")
    if wti_1m is None or wti_1m > -8:
        return None
    return _signal(
        "energy_downside",
        "油價下行，未來一至兩月壓低總體 CPI",
        "能源是總體與核心背離的主因，方向會先反映在總體讀數",
        f"WTI 近一月 {wti_1m:+.1f}%",
        "dovish", "medium", "物價")


@rule
def expectations_unanchored(ctx):
    expectations = ctx["inflation"]["expectations"]
    t5y5y = expectations.get("t5y5y")
    if t5y5y is None or t5y5y < 2.55:
        return None
    return _signal(
        "expectations_unanchored",
        "長期通膨預期開始鬆動",
        "預期一旦脫錨，壓通膨的成本會大幅上升，聯準會會優先處理",
        f"5年後5年期通膨預期 {t5y5y:.2f}%",
        "hawkish", "high", "物價")


@rule
def wages_above_compatible(ctx):
    wages = ctx["inflation"]["wages"]
    gap = wages.get("gap")
    if gap is None or gap < 0.5:
        return None
    return _signal(
        "wages_above_compatible",
        "薪資增速高於生產力所能吸收的水準",
        "薪資減生產力就是單位勞動成本，那是服務業通膨的底線",
        f"時薪年增 {wages['wages']:.1f}%，與 2% 相容水準約 {wages['compatible']:.1f}%",
        "hawkish", "medium", "物價")


# ========================================================== 利率與債務 ======

@rule
def curve_inverted(ctx):
    slope = ctx["rates"]["shape"].get("slope_10_3m")
    if slope is None or slope >= 0:
        return None
    return _signal(
        "curve_inverted",
        "殖利率曲線 10年減3個月倒掛",
        "這條利差是歷史上最可靠的衰退領先指標之一，領先期約 6 至 18 個月",
        f"10年減3個月 {slope:+.2f} 個百分點",
        "dovish", "high", "利率")


@rule
def real_rate_restrictive(ctx):
    real = ctx["rates"]["decomposition"].get("real")
    if real is None or real < 2.0:
        return None
    return _signal(
        "real_rate_restrictive",
        "10年實質利率處於限制性水準",
        "實質利率才是真正的緊縮程度，也是股債估值的分母",
        f"10年實質利率 {real:.2f}%",
        "dovish", "medium", "利率")


@rule
def term_premium_elevated(ctx):
    premium = ctx["rates"]["decomposition"].get("term_premium")
    if premium is None or premium < 0.8:
        return None
    return _signal(
        "term_premium_elevated",
        "期限溢酬偏高，長端在要求額外補償",
        "溢酬上升多半來自供給與財政疑慮，降息也不一定壓得下長端",
        f"期限溢酬（近似）{premium:+.2f} 個百分點",
        "hawkish", "medium", "利率")


@rule
def credit_complacent(ctx):
    rows = ctx["rates"]["credit"]["rows"]
    hy = next((r for r in rows if r["name"] == "高收益"), None)
    if not hy or hy.get("pct10y") is None or hy["pct10y"] > 20:
        return None
    return _signal(
        "credit_complacent",
        "信用利差處在十年低檔，市場幾乎沒有反映風險",
        "利差低檔時，任何壞消息的重定價空間都特別大",
        f"高收益利差 {hy['value']:.2f}%，十年百分位 {hy['pct10y']:.0f}%",
        "neutral", "low", "利率")


@rule
def debt_dynamics_adverse(ctx):
    dynamics = ctx["debt"]["dynamics"]
    r_minus_g = dynamics.get("r_minus_g")
    if r_minus_g is None or r_minus_g <= 0.5:
        return None
    return _signal(
        "debt_dynamics_adverse",
        "實質利率高於實質成長，債務比會自動累積",
        "r 大於 g 時就算基本收支平衡，債務佔 GDP 仍會上升，長端供給只增不減",
        f"r−g 為 {r_minus_g:+.1f} 個百分點，債務佔 GDP {dynamics['debt_gdp']:.0f}%",
        "hawkish", "medium", "債務")


@rule
def interest_burden_rising(ctx):
    fiscal = ctx["debt"]["fiscal"]
    yoy = fiscal.get("interest_yoy")
    if yoy is None or yoy < 10:
        return None
    return _signal(
        "interest_burden_rising",
        "利息支出快速上升，排擠其他財政空間",
        "舊債以更高利率換新債，利息會在高利率環境下持續累積",
        f"聯邦利息支出年增 {yoy:+.0f}%，佔 GDP {fiscal['interest_gdp']:.1f}%"
        if fiscal.get("interest_gdp") is not None else f"聯邦利息支出年增 {yoy:+.0f}%",
        "hawkish", "medium", "債務")


# ============================================================ 成長信用 ======

@rule
def credit_standards_tightening(ctx):
    standards = ctx["growth"]["credit"].get("standards")
    if standards is None or standards < 15:
        return None
    return _signal(
        "credit_standards_tightening",
        "銀行明顯收緊放款標準",
        "信用供給收縮領先就業惡化約二至四個季度",
        f"淨收緊比例 {standards:+.0f}%",
        "dovish", "medium", "成長")


@rule
def consumption_contracting(ctx):
    retail = ctx["growth"]["activity"].get("retail_yoy")
    if retail is None or retail > -0.5:
        return None
    return _signal(
        "consumption_contracting",
        "實質零售銷售年增轉負",
        "消費佔美國 GDP 近七成，實質消費萎縮通常先於衰退",
        f"實質零售銷售年增 {retail:+.1f}%",
        "dovish", "high", "成長")


@rule
def recession_gauge_elevated(ctx):
    gauge = ctx["growth"]["gauge"]
    value = gauge.get("value")
    if value is None or value < 60:
        return None
    severity = "high" if value > 75 else "medium"
    return _signal(
        "recession_gauge_elevated",
        "衰退風險刻度高於常態",
        "多個領先指標同時偏向風險端時，單一指標的雜訊被抵消",
        f"風險刻度 {value:.0f}/100（相對十年常態為「{gauge['level']}」）",
        "dovish", severity, "成長")


# ============================================================== 市場 ========

@rule
def stock_bond_correlation_positive(ctx):
    sb = ctx["market"].get("stock_bond") or {}
    latest = sb.get("latest")
    if latest is None or latest >= -0.15:
        return None
    return _signal(
        "stock_bond_correlation_positive",
        "股債同向，債券失去對沖股票的功能",
        "這是通膨主導的典型特徵，傳統 60/40 配置的分散效果會下降",
        f"標普報酬與10年殖利率變動相關 {latest:+.2f}（近一年）",
        "neutral", "medium", "市場")


@rule
def volatility_complacent(ctx):
    vol = ctx["market"]["volatility"]
    vix = vol.get("vix")
    if vix is None or vix > 15:
        return None
    return _signal(
        "volatility_complacent",
        "波動率處於低檔，市場對總經風險定價不足",
        "低波動本身不是賣訊，但代表壞消息來時的重定價幅度會較大",
        f"VIX {vix:.1f}",
        "neutral", "low", "市場")


# ============================================================== 主入口 ======

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def evaluate(ctx: dict) -> list[dict]:
    """跑完所有規則，依嚴重度排序。"""
    out = []
    for fn in RULES:
        try:
            result = fn(ctx)
        except Exception:
            result = None      # 單條規則的資料缺漏不該讓整份報告掛掉
        if result:
            out.append(result)
    out.sort(key=lambda s: (SEVERITY_ORDER.get(s["severity"], 3), s["key"]))
    return out


def summarise(signals: list[dict]) -> dict:
    hawkish = [s for s in signals if s["direction"] == "hawkish"]
    dovish = [s for s in signals if s["direction"] == "dovish"]
    neutral = [s for s in signals if s["direction"] == "neutral"]
    weights = {"high": 3, "medium": 2, "low": 1}
    score = (sum(weights[s["severity"]] for s in hawkish)
             - sum(weights[s["severity"]] for s in dovish))
    return {
        "total": len(signals),
        "hawkish": len(hawkish), "dovish": len(dovish), "neutral": len(neutral),
        "score": score,
        "tilt": ("偏升息" if score >= 3 else "偏降息" if score <= -3 else "方向分歧"),
    }


def diff(current: list[dict], previous: list[dict] | None) -> dict:
    """與上期比對 — 存檔頁與總覽的『什麼變了』。"""
    if not previous:
        return {"added": [], "removed": [], "same": True, "first_run": True}
    now_keys = {s["key"] for s in current}
    old_keys = {s["key"] for s in previous}
    added = [s for s in current if s["key"] not in old_keys]
    removed = [s for s in previous if s["key"] not in now_keys]
    return {"added": added, "removed": removed,
            "same": not added and not removed, "first_run": False}
