"""The indicator catalogue.

Every series the dashboard uses, with its Chinese label, unit and frequency
declared up front. Declaring unit/frequency here rather than reading FRED's
metadata endpoint halves the number of API calls a build makes, which matters
because FRED throttles hard.

Fields: id -> (中文名, unit, frequency, start)
  unit      free text, shown in the UI
  frequency d | w | m | q | a  (drives yoy()/annualised() period counts)
"""
from __future__ import annotations

Spec = tuple[str, str, str, str]

DEFAULT_START = "1990-01-01"
LONG_START = "1960-01-01"

# ------------------------------------------------------------------ 勞動市場 --
LABOR: dict[str, Spec] = {
    "PAYEMS":        ("非農就業總數", "千人", "m", LONG_START),
    "USPRIV":        ("民間部門就業", "千人", "m", LONG_START),
    "UNRATE":        ("失業率", "%", "m", LONG_START),
    "U6RATE":        ("U6 廣義失業率", "%", "m", "1994-01-01"),
    "CIVPART":       ("勞動參與率", "%", "m", LONG_START),
    "EMRATIO":       ("就業人口比", "%", "m", LONG_START),
    "LNS11300060":   ("黃金年齡勞參率 25-54", "%", "m", LONG_START),
    "LNS12300060":   ("黃金年齡就業率 25-54", "%", "m", LONG_START),
    "CES0500000003": ("平均時薪", "美元", "m", "2006-01-01"),
    "AWHAETP":       ("平均週工時", "小時", "m", "2006-01-01"),
    "AWHMAN":        ("製造業週工時", "小時", "m", LONG_START),
    "ICSA":          ("初領失業金", "人", "w", "2000-01-01"),
    "IC4WSA":        ("初領失業金四週均", "人", "w", "2000-01-01"),
    "CCSA":          ("續領失業金", "人", "w", "2000-01-01"),
    "JTSJOL":        ("職缺數", "千個", "m", "2000-12-01"),
    "JTSHIR":        ("招聘數", "千人", "m", "2000-12-01"),
    "JTSQUR":        ("主動離職率", "%", "m", "2000-12-01"),
    "JTSLDR":        ("裁員率", "%", "m", "2000-12-01"),
    "JTSTSR":        ("總離職率", "%", "m", "2000-12-01"),
    "UEMPMED":       ("失業期間中位數", "週", "m", LONG_START),
    "UEMPMEAN":      ("失業期間平均", "週", "m", LONG_START),
    "LNS13023621":   ("失業-被裁員", "千人", "m", LONG_START),
    "LNS13023557":   ("失業-重返勞動力", "千人", "m", LONG_START),
    "LNS12032194":   ("經濟因素兼職", "千人", "m", LONG_START),
    "NROU":          ("自然失業率估計", "%", "q", LONG_START),
    "CNP16OV":       ("民間非機構人口", "千人", "m", LONG_START),
    "CLF16OV":       ("勞動力人口", "千人", "m", LONG_START),
    "CE16OV":        ("就業人口", "千人", "m", LONG_START),
    "UNEMPLOY":      ("失業人口", "千人", "m", LONG_START),
    "OPHNFB":        ("非農生產力", "指數", "q", LONG_START),
    "ULCNFB":        ("單位勞動成本", "指數", "q", LONG_START),
    "LNS13008397":   ("短期失業佔比 <5週", "%", "m", LONG_START),
    "LNS13026511":   ("永久性失業佔比", "%", "m", LONG_START),
}

# 行業別就業 — 用於貢獻拆解
LABOR_SECTORS: dict[str, str] = {
    "USCONS":        "營建",
    "MANEMP":        "製造",
    "USMINE":        "礦業與伐木",
    "USWTRADE":      "批發",
    "USTRADE":       "零售",
    "CES4300000001": "運輸倉儲",
    "USINFO":        "資訊",
    "USFIRE":        "金融",
    "USPBS":         "專業與商業服務",
    "CES6562000101": "醫療照護",
    "USEHS":         "教育與健康",
    "USLAH":         "休閒住宿餐飲",
    "USSERV":        "其他服務",
    "USGOVT":        "政府",
    "CES9091000001": "聯邦政府",
}

# ---------------------------------------------------------------- 通膨 --------
INFLATION: dict[str, Spec] = {
    "CPIAUCSL":     ("CPI 總體", "指數", "m", LONG_START),
    "CPILFESL":     ("核心 CPI", "指數", "m", LONG_START),
    # BLS 新聞稿的年增率用「未季調」指數算。標題數字用這兩檔才對得上
    # 官方發布；季調版留給月增動能與分項貢獻（那裡才需要去季節性）。
    "CPIAUCNS":     ("CPI 總體（未季調）", "指數", "m", LONG_START),
    "CPILFENS":     ("核心 CPI（未季調）", "指數", "m", LONG_START),
    "PCEPI":        ("PCE 物價", "指數", "m", LONG_START),
    "PCEPILFE":     ("核心 PCE", "指數", "m", LONG_START),
    "CPIUFDSL":     ("食物 CPI", "指數", "m", LONG_START),
    "CPIENGSL":     ("能源 CPI", "指數", "m", LONG_START),
    "CUSR0000SAH1": ("住房", "指數", "m", LONG_START),
    "CUSR0000SEHA": ("主要住所租金", "指數", "m", LONG_START),
    "CUSR0000SEHC": ("業主約當租金", "指數", "m", LONG_START),
    "CUSR0000SAS":  ("服務", "指數", "m", LONG_START),
    "CUSR0000SAD":  ("耐久財", "指數", "m", LONG_START),
    "CUSR0000SAN":  ("非耐久財", "指數", "m", LONG_START),
    "CUSR0000SETA01": ("新車", "指數", "m", LONG_START),
    "CUSR0000SETA02": ("二手車", "指數", "m", LONG_START),
    "CUSR0000SAF11":  ("家中食物", "指數", "m", LONG_START),
    "CUSR0000SAS4":   ("運輸服務", "指數", "m", LONG_START),
    "CUSR0000SAM2":   ("醫療服務", "指數", "m", LONG_START),
    "MEDCPIM158SFRBCLE":     ("中位數 CPI", "%", "m", LONG_START),
    "TRMMEANCPIM158SFRBCLE": ("截尾平均 CPI", "%", "m", LONG_START),
    "CORESTICKM159SFRBATL":  ("黏性核心 CPI", "%", "m", LONG_START),
    "STICKCPIM159SFRBATL":   ("黏性 CPI", "%", "m", LONG_START),
    "T5YIFR":   ("5年後5年通膨預期", "%", "d", "2003-01-01"),
    "T5YIE":    ("5年通膨補償", "%", "d", "2003-01-01"),
    "T10YIE":   ("10年通膨補償", "%", "d", "2003-01-01"),
    "MICH":     ("密大1年通膨預期", "%", "m", LONG_START),
    "EXPINF1YR":  ("克里夫蘭聯準1年預期", "%", "m", "1982-01-01"),
    "EXPINF5YR":  ("克里夫蘭聯準5年預期", "%", "m", "1982-01-01"),
    "EXPINF10YR": ("克里夫蘭聯準10年預期", "%", "m", "1982-01-01"),
    "ECIALLCIV": ("僱用成本指數", "指數", "q", LONG_START),
    "ECIWAG":    ("僱用成本-薪資", "指數", "q", LONG_START),
    "PPIACO":    ("PPI 全商品", "指數", "m", LONG_START),
    "PPIFIS":    ("PPI 最終需求", "指數", "m", "2009-01-01"),
    "DCOILWTICO": ("WTI 原油", "美元/桶", "d", "1990-01-01"),
    "DCOILBRENTEU": ("布蘭特原油", "美元/桶", "d", "1990-01-01"),
    "GASREGW":   ("零售汽油", "美元/加侖", "w", "1995-01-01"),
    "DHHNGSP":   ("天然氣 Henry Hub", "美元/MMBtu", "d", "1997-01-01"),
    "PALLFNFINDEXM": ("全球商品價格指數", "指數", "m", LONG_START),
    "PNRGINDEXM":    ("全球能源價格指數", "指數", "m", LONG_START),
}

# CPI 分項權重（BLS relative importance，近似值，用於貢獻拆解）
CPI_WEIGHTS: dict[str, tuple[str, float]] = {
    "CUSR0000SAH1":   ("住房", 35.2),
    "CUSR0000SAF11":  ("家中食物", 8.1),
    "CUSR0000SAS4":   ("運輸服務", 6.5),
    "CUSR0000SAM2":   ("醫療服務", 6.7),
    "CUSR0000SETA01": ("新車", 3.6),
    "CUSR0000SETA02": ("二手車", 2.0),
    "CPIENGSL":       ("能源", 6.2),
}

# ------------------------------------------------------- 聯準會、利率、債務 --
RATES: dict[str, Spec] = {
    "DFF":       ("聯邦資金有效利率", "%", "d", LONG_START),
    "DFEDTARU":  ("政策利率上緣", "%", "d", "2008-12-01"),
    "DFEDTARL":  ("政策利率下緣", "%", "d", "2008-12-01"),
    "SOFR":      ("SOFR", "%", "d", "2018-04-01"),
    "DGS1MO":    ("1個月", "%", "d", "2001-07-01"),
    "DGS3MO":    ("3個月", "%", "d", "1990-01-01"),
    "DGS6MO":    ("6個月", "%", "d", "1990-01-01"),
    "DGS1":      ("1年", "%", "d", "1990-01-01"),
    "DGS2":      ("2年", "%", "d", "1990-01-01"),
    "DGS3":      ("3年", "%", "d", "1990-01-01"),
    "DGS5":      ("5年", "%", "d", "1990-01-01"),
    "DGS7":      ("7年", "%", "d", "1990-01-01"),
    "DGS10":     ("10年", "%", "d", "1990-01-01"),
    "DGS20":     ("20年", "%", "d", "1993-10-01"),
    "DGS30":     ("30年", "%", "d", "1990-01-01"),
    "DFII5":     ("5年實質", "%", "d", "2003-01-01"),
    "DFII10":    ("10年實質", "%", "d", "2003-01-01"),
    "DFII30":    ("30年實質", "%", "d", "2010-02-01"),
    "T10Y2Y":    ("10年減2年", "%", "d", "1990-01-01"),
    "T10Y3M":    ("10年減3個月", "%", "d", "1990-01-01"),
    "BAMLC0A0CM":    ("投資級利差", "%", "d", "1996-12-01"),
    "BAMLC0A1CAAA":  ("AAA 利差", "%", "d", "1996-12-01"),
    "BAMLC0A4CBBB":  ("BBB 利差", "%", "d", "1996-12-01"),
    "BAMLH0A0HYM2":  ("高收益利差", "%", "d", "1996-12-01"),
    "BAMLEMCBPIOAS": ("新興市場利差", "%", "d", "1998-12-31"),
    "NFCI":      ("芝加哥聯準金融情勢", "指數", "w", LONG_START),
    "ANFCI":     ("調整後金融情勢", "指數", "w", LONG_START),
    "STLFSI4":   ("聖路易聯準金融壓力", "指數", "w", "1993-12-31"),
    "MORTGAGE30US": ("30年房貸利率", "%", "w", LONG_START),
    "WALCL":     ("聯準會總資產", "百萬美元", "w", "2002-12-18"),
    "RRPONTSYD": ("隔夜逆回購", "十億美元", "d", "2003-02-07"),
    "WTREGEN":   ("財政部一般帳戶", "十億美元", "w", "2002-12-18"),
}

DEBT: dict[str, Spec] = {
    "GFDEGDQ188S": ("聯邦債務佔 GDP", "%", "q", LONG_START),
    "GFDEBTN":     ("聯邦債務總額", "百萬美元", "q", LONG_START),
    "FYFSGDA188S": ("財政赤字佔 GDP", "%", "a", LONG_START),
    "MTSDS133FMS": ("月度財政收支", "百萬美元", "m", LONG_START),
    "A091RC1Q027SBEA": ("聯邦利息支出", "十億美元", "q", LONG_START),
    "FYOIGDA188S": ("利息支出佔 GDP", "%", "a", LONG_START),
    "FDHBFIN":     ("外國持有美債", "百萬美元", "q", LONG_START),
    "FDHBPIN":     ("民間持有美債", "百萬美元", "q", LONG_START),
}

# ------------------------------------------------------------ 成長與信用 -----
GROWTH: dict[str, Spec] = {
    "GDPC1":          ("實質 GDP", "十億美元", "q", LONG_START),
    "A191RL1Q225SBEA": ("實質 GDP 年化季增", "%", "q", LONG_START),
    "INDPRO":         ("工業生產", "指數", "m", LONG_START),
    "TCU":            ("產能利用率", "%", "m", LONG_START),
    "RSAFS":          ("零售銷售", "百萬美元", "m", "1992-01-01"),
    "RRSFS":          ("實質零售銷售", "百萬美元", "m", "1992-01-01"),
    "PCEC96":         ("實質個人消費", "十億美元", "m", LONG_START),
    "DSPIC96":        ("實質可支配所得", "十億美元", "m", LONG_START),
    "PSAVERT":        ("儲蓄率", "%", "m", LONG_START),
    "HOUST":          ("新屋開工", "千戶", "m", LONG_START),
    "PERMIT":         ("建築許可", "千戶", "m", LONG_START),
    "UMCSENT":        ("密大消費者信心", "指數", "m", LONG_START),
    "TOTALSA":        ("汽車銷售", "百萬輛", "m", LONG_START),
    "DGORDER":        ("耐久財訂單", "百萬美元", "m", "1992-02-01"),
    "NEWORDER":       ("核心資本財訂單", "百萬美元", "m", "1992-02-01"),
    "SAHMREALTIME":   ("Sahm 法則即時值", "%", "m", LONG_START),
    "M2SL":           ("M2 貨幣供給", "十億美元", "m", LONG_START),
    "BUSLOANS":       ("工商放款", "十億美元", "m", LONG_START),
    "DRTSCILM":       ("放款標準收緊比例", "%", "q", "1990-04-01"),
    "DRCCLACBS":      ("信用卡違約率", "%", "q", "1991-01-01"),
    "DRSFRMACBS":     ("房貸違約率", "%", "q", "1991-01-01"),
    "DRBLACBS":       ("商業放款違約率", "%", "q", "1987-01-01"),
    "TDSP":           ("家庭債務負擔比", "%", "q", "1980-01-01"),
    "GPDIC1":         ("實質民間投資", "十億美元", "q", LONG_START),
}

# ------------------------------------------------------------ 全球對照 -------
# 只列實測仍在更新的序列。FRED 上 OECD 來源的 MEI 系列多已凍結
# （日本 CPI 停在 2021、中國 2025-04、英國 2025-03、台灣從缺），
# 因此各國 CPI 改由 OECD SDMX 直接取，歐元區失業率由 ECB 取。
GLOBAL_BLOCKS: dict[str, dict] = {
    "US": {"name": "美國", "oecd": "USA", "unemp": "UNRATE",
           "policy": "DFEDTARU", "long": "DGS10", "fx": None},
    "EA": {"name": "歐元區", "oecd": None, "unemp": None,
           "policy": "ECBDFR", "long": "IRLTLT01DEM156N", "fx": "DEXUSEU"},
    "DE": {"name": "德國", "oecd": "DEU", "unemp": None,
           "policy": None, "long": "IRLTLT01DEM156N", "fx": None},
    "JP": {"name": "日本", "oecd": "JPN", "unemp": "LRUN64TTJPM156S",
           "policy": None, "long": "IRLTLT01JPM156N", "fx": "DEXJPUS"},
    "GB": {"name": "英國", "oecd": "GBR", "unemp": "LRHUTTTTGBM156S",
           "policy": None, "long": "IRLTLT01GBM156N", "fx": "DEXUSUK"},
    "CN": {"name": "中國", "oecd": "CHN", "unemp": None,
           "policy": None, "long": None, "fx": "DEXCHUS"},
    "KR": {"name": "南韓", "oecd": "KOR", "unemp": None,
           "policy": None, "long": "IRLTLT01KRM156N", "fx": "DEXKOUS"},
    "CA": {"name": "加拿大", "oecd": "CAN", "unemp": None,
           "policy": None, "long": "IRLTLT01CAM156N", "fx": "DEXCAUS"},
    "AU": {"name": "澳洲", "oecd": "AUS", "unemp": None,
           "policy": None, "long": "IRLTLT01AUM156N", "fx": None},
    "TW": {"name": "台灣", "oecd": None, "unemp": None,
           "policy": None, "long": None, "fx": "DEXTAUS"},
}

# OECD SDMX 一次取回多國 CPI 年增率
OECD_CPI_AREAS = ["DEU", "GBR", "CHN", "KOR", "CAN", "AUS", "FRA", "ITA", "ESP", "JPN"]

GLOBAL_SERIES: dict[str, Spec] = {
    "CP0000EZ19M086NEST": ("歐元區 HICP", "指數", "m", LONG_START),
    "ECBDFR":             ("ECB 存款利率", "%", "d", LONG_START),
    "ECBMRRFR":           ("ECB 主要再融資利率", "%", "d", LONG_START),
    "CLVMNACSCAB1GQEA19": ("歐元區實質 GDP", "百萬歐元", "q", LONG_START),
    "IRLTLT01DEM156N":    ("德國10年", "%", "m", LONG_START),
    "IRLTLT01JPM156N":    ("日本10年", "%", "m", LONG_START),
    "IRLTLT01GBM156N":    ("英國10年", "%", "m", LONG_START),
    "IRLTLT01ITM156N":    ("義大利10年", "%", "m", LONG_START),
    "IRLTLT01FRM156N":    ("法國10年", "%", "m", LONG_START),
    "IRLTLT01CAM156N":    ("加拿大10年", "%", "m", LONG_START),
    "IRLTLT01KRM156N":    ("南韓10年", "%", "m", LONG_START),
    "IRLTLT01AUM156N":    ("澳洲10年", "%", "m", LONG_START),
    "LRUN64TTJPM156S":    ("日本失業率", "%", "m", LONG_START),
    "LRHUTTTTGBM156S":    ("英國失業率", "%", "m", LONG_START),
    "JPNRGDPEXP":         ("日本實質 GDP", "十億日圓", "q", LONG_START),
    "DEXJPUS":  ("美元兌日圓", "JPY", "d", LONG_START),
    "DEXCHUS":  ("美元兌人民幣", "CNY", "d", LONG_START),
    "DEXUSEU":  ("歐元兌美元", "USD", "d", "1999-01-04"),
    "DEXUSUK":  ("英鎊兌美元", "USD", "d", LONG_START),
    "DEXKOUS":  ("美元兌韓元", "KRW", "d", LONG_START),
    "DEXTAUS":  ("美元兌新台幣", "TWD", "d", LONG_START),
    "DEXCAUS":  ("美元兌加幣", "CAD", "d", LONG_START),
    "DEXSZUS":  ("美元兌瑞郎", "CHF", "d", LONG_START),
    "DEXINUS":  ("美元兌印度盧比", "INR", "d", LONG_START),
    "DTWEXBGS": ("美元指數（廣義）", "指數", "d", "2006-01-02"),
    "DTWEXAFEGS": ("美元指數（先進國）", "指數", "d", "2006-01-02"),
    "DTWEXEMEGS": ("美元指數（新興市場）", "指數", "d", "2006-01-02"),
}

# ------------------------------------------------------------- 市場面 -------
MARKET: dict[str, Spec] = {
    "SP500":      ("標普 500", "點", "d", "2015-01-01"),
    "NASDAQCOM":  ("那斯達克綜合", "點", "d", "1990-01-01"),
    "DJIA":       ("道瓊工業", "點", "d", "1990-01-01"),
    "VIXCLS":     ("VIX 波動率", "指數", "d", "1990-01-01"),
    "VXNCLS":     ("那斯達克波動率", "指數", "d", "2001-02-02"),
    "OVXCLS":     ("原油波動率", "指數", "d", "2007-05-10"),
    "GVZCLS":     ("黃金波動率", "指數", "d", "2008-06-03"),
    "CBBTCUSD":   ("比特幣", "美元", "d", "2014-12-01"),
    "CBETHUSD":   ("以太幣", "美元", "d", "2016-05-01"),
}

# ---------------------------------------------------------- 大宗商品 --------
# 金銀走 LBMA 官方定盤價（FRED 的黃金序列 2023 年已停更）；
# 其餘走 FRED 上的 IMF Primary Commodity Prices。
COMMODITIES: dict[str, Spec] = {
    # 能源
    "DCOILWTICO":   ("WTI 原油", "美元/桶", "d", "1990-01-01"),
    "DCOILBRENTEU": ("布蘭特原油", "美元/桶", "d", "1990-01-01"),
    "DHHNGSP":      ("天然氣 Henry Hub", "美元/MMBtu", "d", "1997-01-01"),
    "GASREGW":      ("零售汽油", "美元/加侖", "w", "1995-01-01"),
    # 工業金屬
    "PCOPPUSDM":    ("銅", "美元/噸", "m", LONG_START),
    "PALUMUSDM":    ("鋁", "美元/噸", "m", LONG_START),
    "PNICKUSDM":    ("鎳", "美元/噸", "m", LONG_START),
    # 農產
    "PWHEAMTUSDM":  ("小麥", "美元/噸", "m", LONG_START),
    "PMAIZMTUSDM":  ("玉米", "美元/噸", "m", LONG_START),
    "PSOYBUSDM":    ("黃豆", "美元/噸", "m", LONG_START),
    # 指數
    "PALLFNFINDEXM": ("全商品指數", "指數", "m", LONG_START),
    "PNRGINDEXM":    ("能源指數", "指數", "m", LONG_START),
    "PMETAINDEXM":   ("金屬指數", "指數", "m", LONG_START),
    "PINDUINDEXM":   ("工業原料指數", "指數", "m", LONG_START),
    "PFOODINDEXM":   ("食品指數", "指數", "m", LONG_START),
    "PRAWMINDEXM":   ("農業原料指數", "指數", "m", LONG_START),
}

COMMODITY_GROUPS = [
    ("能源", ["DCOILWTICO", "DCOILBRENTEU", "DHHNGSP", "GASREGW"]),
    ("工業金屬", ["PCOPPUSDM", "PALUMUSDM", "PNICKUSDM"]),
    ("農產", ["PWHEAMTUSDM", "PMAIZMTUSDM", "PSOYBUSDM"]),
    ("指數", ["PALLFNFINDEXM", "PNRGINDEXM", "PMETAINDEXM", "PINDUINDEXM",
              "PFOODINDEXM", "PRAWMINDEXM"]),
]

ALL_GROUPS = {
    "labor": LABOR, "inflation": INFLATION, "rates": RATES, "debt": DEBT,
    "growth": GROWTH, "global": GLOBAL_SERIES, "market": MARKET,
    "commodities": COMMODITIES,
}


def sector_specs() -> dict[str, Spec]:
    return {sid: (name, "千人", "m", LONG_START) for sid, name in LABOR_SECTORS.items()}
