"""全球對照。

資料源分工是被迫的：FRED 上 OECD 來源的國際 MEI 序列多已凍結
（日本 CPI 停在 2021-06、中國停在 2025-04、台灣從缺），所以各國 CPI 走
OECD SDMX、歐元區失業率走 ECB，長天期公債殖利率與匯率仍走 FRED。
每一格都帶自己的 as-of 日期，過期的會標出來，不會用舊值假裝是現況。
"""
from __future__ import annotations

from datetime import date

from .. import catalogue
from ..data import Bundle
from ..series import Series, EMPTY
from ..sources import sdmx, taiwan

OECD_PRICES = (sdmx.OECD_BASE +
               "/OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0/"
               "{areas}.M.N.CPI.PA._T.N.GY?format=jsondata&startPeriod=2010-01")
ECB_UNEMPLOYMENT = (sdmx.ECB_BASE +
                    "/LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T?format=jsondata&startPeriod=2010-01")
ECB_HICP_CORE = (sdmx.ECB_BASE +
                 "/ICP/M.U2.N.XEF000.4.ANR?format=jsondata&startPeriod=2010-01")

STALE_DAYS = 150


def fetch_external() -> dict:
    """OECD 各國 CPI 年增率 + ECB 歐元區失業率與核心 HICP。"""
    areas = "+".join(catalogue.OECD_CPI_AREAS)
    cpi = sdmx.by_area(OECD_PRICES.format(areas=areas), unit="%", frequency="m")
    unemployment = sdmx.one(ECB_UNEMPLOYMENT, series_id="EA_UNEMP",
                            label="歐元區失業率", unit="%", frequency="m", source="ECB")
    core_hicp = sdmx.one(ECB_HICP_CORE, series_id="EA_CORE_HICP",
                         label="歐元區核心 HICP", unit="%", frequency="m", source="ECB")
    # 台灣既不在 FRED 也不在 OECD，直接接主計總處的公開資料。
    tw = taiwan.cpi()
    return {"cpi": cpi, "ea_unemployment": unemployment, "ea_core": core_hicp,
            "tw_cpi": tw["yoy"], "tw_cpi_index": tw["index"]}


def _staleness(last: date | None, today: date) -> tuple[bool, int | None]:
    if last is None:
        return True, None
    age = (today - last).days
    return age > STALE_DAYS, age


def country_table(bundle: Bundle, external: dict) -> dict:
    today = date.today()
    rows = []
    for code, block in catalogue.GLOBAL_BLOCKS.items():
        cpi_value = cpi_date = None
        cpi_series: Series = EMPTY

        if code == "US":
            series = bundle["CPIAUCSL"].yoy()
            cpi_value, cpi_date, cpi_series = series.last, series.last_date, series
        elif code == "EA":
            hicp = bundle["CP0000EZ19M086NEST"].yoy()
            cpi_value, cpi_date, cpi_series = hicp.last, hicp.last_date, hicp
        elif code == "TW":
            tw = external.get("tw_cpi") or EMPTY
            cpi_value, cpi_date, cpi_series = tw.last, tw.last_date, tw
        elif block.get("oecd"):
            series = external["cpi"].get(block["oecd"], EMPTY)
            cpi_value, cpi_date, cpi_series = series.last, series.last_date, series

        unemployment = unemployment_date = None
        if code == "EA":
            s = external["ea_unemployment"]
            unemployment, unemployment_date = s.last, s.last_date
        elif block.get("unemp"):
            s = bundle[block["unemp"]]
            unemployment, unemployment_date = s.last, s.last_date

        long_yield = long_date = None
        if block.get("long"):
            s = bundle[block["long"]]
            long_yield, long_date = s.last, s.last_date

        policy = None
        if block.get("policy"):
            policy = bundle[block["policy"]].last

        fx = fx_chg = None
        if block.get("fx"):
            s = bundle[block["fx"]]
            fx = s.last
            year_ago = s.at(-253)
            if fx is not None and year_ago:
                fx_chg = (fx / year_ago - 1) * 100

        stale, age = _staleness(cpi_date, today)
        rows.append({
            "code": code, "name": block["name"],
            "cpi": cpi_value, "cpi_date": cpi_date, "cpi_stale": stale, "cpi_age": age,
            "cpi_series": cpi_series,
            "unemployment": unemployment, "unemployment_date": unemployment_date,
            "long": long_yield, "long_date": long_date,
            "policy": policy,
            "fx": fx, "fx_chg_1y": fx_chg,
            # 停更的 CPI 不拿來算實質殖利率：用五年前的通膨減今天的殖利率，
            # 得到的數字看起來精確，其實沒有意義。
            "real_yield": (long_yield - cpi_value)
                          if (long_yield is not None and cpi_value is not None
                              and not stale) else None,
        })
    return {"rows": rows}


def dollar(bundle: Bundle) -> dict:
    broad = bundle["DTWEXBGS"]
    advanced = bundle["DTWEXAFEGS"]
    emerging = bundle["DTWEXEMEGS"]

    def change(s: Series, periods: int):
        prior = s.at(-1 - periods)
        return ((s.last / prior - 1) * 100) if (s.last and prior) else None

    return {
        "broad": broad.last, "broad_series": broad,
        "advanced": advanced.last, "emerging": emerging.last,
        "chg_1m": change(broad, 21), "chg_3m": change(broad, 63),
        "chg_1y": change(broad, 252),
        "pct10y": broad.percentile_rank(10),
        "as_of": broad.last_date,
    }


def fx_table(bundle: Bundle) -> dict:
    pairs = [
        ("DEXJPUS", "美元/日圓", False), ("DEXUSEU", "歐元/美元", True),
        ("DEXUSUK", "英鎊/美元", True), ("DEXCHUS", "美元/人民幣", False),
        ("DEXTAUS", "美元/新台幣", False), ("DEXKOUS", "美元/韓元", False),
        ("DEXCAUS", "美元/加幣", False), ("DEXSZUS", "美元/瑞郎", False),
        ("DEXINUS", "美元/印度盧比", False),
    ]
    rows = []
    for series_id, name, inverted in pairs:
        s = bundle[series_id]
        if not s:
            continue

        def change(periods):
            prior = s.at(-1 - periods)
            if not (s.last and prior):
                return None
            move = (s.last / prior - 1) * 100
            # 一律以「美元強弱」為方向：報價是外幣/美元時要反號
            return -move if inverted else move

        rows.append({
            "name": name, "value": s.last,
            "chg_1m": change(21), "chg_3m": change(63), "chg_1y": change(252),
            "series": s,
        })
    return {"rows": rows, "as_of": bundle["DEXJPUS"].last_date}


def divergence(rows: list[dict]) -> dict:
    """各國通膨與政策的分歧程度 — 決定匯率與跨國利差的張力。"""
    cpis = [r["cpi"] for r in rows if r["cpi"] is not None and not r["cpi_stale"]]
    yields_ = [r["long"] for r in rows if r["long"] is not None]
    if len(cpis) < 3:
        return {}
    spread = max(cpis) - min(cpis)
    return {
        "cpi_spread": spread,
        "cpi_avg": sum(cpis) / len(cpis),
        "yield_spread": (max(yields_) - min(yields_)) if len(yields_) >= 3 else None,
        "n": len(cpis),
        "verdict": ("各國通膨分歧大，政策難以同步" if spread > 2.0
                    else "各國通膨大致收斂" if spread < 1.0
                    else "各國通膨分歧中等"),
    }


def compute(bundle: Bundle) -> dict:
    external = fetch_external()
    table = country_table(bundle, external)
    return {
        "as_of": bundle["DEXJPUS"].last_date,
        "countries": table,
        "dollar": dollar(bundle),
        "fx": fx_table(bundle),
        "divergence": divergence(table["rows"]),
        "ea_core": external["ea_core"].last,
        "ea_core_series": external["ea_core"],
        "gaps": [r["name"] for r in table["rows"] if r["cpi"] is None],
        "stale": [(r["name"], r["cpi_date"]) for r in table["rows"]
                  if r["cpi_stale"] and r["cpi"] is not None],
    }
