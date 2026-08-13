"""股市報價頁：美股、台股、其他新興市場。"""
from __future__ import annotations

from ..common import hbar_chart, line_chart
from ..html import (callout, delta_span, esc, fmt, section, stat, table,
                    zh_date)


def _stamp(rows: list[dict]) -> str:
    when = next((r["quoted_at"] for r in rows if r.get("quoted_at")), None)
    return when.strftime("%Y-%m-%d %H:%M") if when else "—"


def _live(symbol: str, field: str, market: str, digits: int, inner: str) -> str:
    """把一個數字包成可被 quotes.js 就地更新的欄位。

    沒有報價代理時這些屬性只是死的標記，頁面照樣顯示建置時的快照。
    """
    return (f'<span data-quote="{esc(symbol)}" data-field="{esc(field)}" '
            f'data-market="{esc(market)}" data-digits="{digits}">{inner}</span>')


def _quote_table(rows: list[dict], *, with_limits: bool = False,
                 price_digits: int = 2, market: str = "other") -> str:
    headers = ["名稱", "代號", "價格", "漲跌", "漲跌幅", "開盤", "最高", "最低", "昨收"]
    if with_limits:
        headers += ["漲停", "跌停"]
    body = []
    for r in rows:
        symbol = str(r["symbol"])
        row = [
            esc(r["name"]), esc(symbol),
            "<strong>" + _live(symbol, "price", market, price_digits,
                               fmt(r["price"], price_digits)) + "</strong>",
            _live(symbol, "change", market, price_digits,
                  delta_span(r["change"], price_digits)),
            _live(symbol, "change_percent", market, 2,
                  delta_span(r["change_percent"], 2, suffix="%")),
            fmt(r["open"], price_digits),
            _live(symbol, "high", market, price_digits, fmt(r["high"], price_digits)),
            _live(symbol, "low", market, price_digits, fmt(r["low"], price_digits)),
            fmt(r["previous_close"], price_digits),
        ]
        if with_limits:
            row += [fmt(r["limit_up"], price_digits), fmt(r["limit_down"], price_digits)]
        body.append(row)
    return table(headers, body)


def _breadth_line(breadth: dict, label: str) -> str:
    if not breadth:
        return ""
    return callout(
        f'{esc(label)}：{breadth["up"]} 檔上漲、{breadth["down"]} 檔下跌，'
        f'平均 {fmt(breadth["average"], 2, suffix="%", signed=True)}。'
        f'最強 {esc(breadth["best"]["name"])} '
        f'{fmt(breadth["best"]["change_percent"], 2, suffix="%", signed=True)}，'
        f'最弱 {esc(breadth["worst"]["name"])} '
        f'{fmt(breadth["worst"]["change_percent"], 2, suffix="%", signed=True)}。')


def _movers_chart(rows: list[dict], title: str, sub: str = "") -> str:
    data = [{"name": r["name"], "value": r["change_percent"]}
            for r in rows if r.get("change_percent") is not None]
    if not data:
        return ""
    data.sort(key=lambda r: r["value"], reverse=True)
    return hbar_chart(title, data, suffix="%", digits=2, label_width=110,
                      sub=sub or "顏色只標漲跌")


def heat_style(pct) -> str:
    """漲跌幅 → 磁磚底色。±3% 封頂，之內線性調透明度。

    quotes.js 的 heatColor() 是同一套公式——建置快照與即時更新
    看起來必須是同一種顏色，改這裡就要一起改那裡。
    顏色沿用全站慣例：綠漲紅跌（.pos/.neg 同色系）。
    """
    if pct is None:
        return "background:rgba(137,135,129,0.10)"
    clamped = max(-3.0, min(3.0, pct))
    alpha = 0.06 + abs(clamped) / 3.0 * 0.42
    rgb = "12,132,58" if clamped > 0 else "199,55,55" if clamped < 0 else "137,135,129"
    return f"background:rgba({rgb},{alpha:.3f})"


def _heatmap(groups: list[dict]) -> str:
    """族群熱力圖：每個族群一列標籤 + 一片磁磚。

    磁磚上是名稱、代號與漲跌幅；漲跌幅欄位帶 data-quote，跟表格
    共用同一套即時更新；磁磚本身帶 data-heat，quotes.js 會依新的
    漲跌幅重刷底色。
    """
    blocks = []
    for group in groups:
        if not group["rows"]:
            continue
        moves = [r["change_percent"] for r in group["rows"]
                 if r.get("change_percent") is not None]
        avg = sum(moves) / len(moves) if moves else None
        tiles = []
        for r in group["rows"]:
            symbol = str(r["symbol"])
            tiles.append(
                f'<div class="heat-tile" data-heat="{esc(symbol)}" '
                f'style="{heat_style(r.get("change_percent"))}">'
                f'<span class="ht-name">{esc(r["name"])}</span>'
                f'<span class="ht-code">{esc(symbol)}</span>'
                f'<span class="ht-chg">'
                + _live(symbol, "change_percent", "tw", 2,
                        delta_span(r.get("change_percent"), 2, suffix="%"))
                + "</span></div>")
        blocks.append(
            f'<div class="heat-group">'
            f'<div class="heat-label"><span>{esc(group["name"])}</span>'
            f'<span class="heat-avg">{fmt(avg, 2, suffix="%", signed=True)}</span></div>'
            f'<div class="heat-tiles">{"".join(tiles)}</div></div>')
    return f'<div class="heatmap">{"".join(blocks)}</div>'


def _watchlist(market: str) -> str:
    """自選清單容器。列是空的——quotes.js 讀 localStorage 後動態生成，
    生成的儲存格帶 data-quote 屬性，跟其他表格共用同一套即時更新。

    沒有帳號系統是刻意的：清單存瀏覽器本機，不上傳、不跨裝置，
    網站本身維持純靜態。
    """
    name_col = "<th>名稱</th>" if market == "tw" else ""
    hint = ("輸入證交所代號（2330、00878、8299…含上櫃）"
            if market == "tw" else
            "輸入美股代號（AAPL、SPY、QQQ…）；^ 開頭的指數不支援，請用對應 ETF")
    return (
        f'<div data-watchlist="{market}">'
        f'<div data-account-slot></div>'
        f'<form class="wl-form" data-wl-form>'
        f'<input class="wl-input" maxlength="10" autocomplete="off" '
        f'placeholder="{esc(hint)}" aria-label="新增自選代號">'
        f'<button type="submit" class="wl-add">加入</button>'
        f'<span class="wl-msg" aria-live="polite"></span></form>'
        f'<div class="table-wrap"><table><thead><tr>'
        f'<th>代號</th>{name_col}<th>成交</th><th>漲跌</th><th>漲跌幅</th>'
        f'<th>昨收</th><th></th></tr></thead><tbody></tbody></table></div>'
        f'<p class="wl-empty muted">還沒有自選。加入的清單只存在這個瀏覽器'
        f'（localStorage），換裝置或清瀏覽資料就會不見。</p></div>')


def _status_note(status: str, source: str) -> str:
    return (f'<p class="muted" style="font-size:.83rem;margin:-4px 0 12px">'
            f'狀態：{esc(status)}　·　來源：{esc(source)}</p>')


def render_us(ctx: dict) -> str:
    d = ctx.get("equities") or {}
    body = []

    if not d.get("available"):
        return ('<div class="card"><p class="muted">'
                '報價來源目前不可用。指數需要 Fincept Terminal（預設在 '
                '<code>~/Desktop/fincept-mcp</code>，可用環境變數 '
                '<code>FINCEPT_ROOT</code> 指定其他位置）。</p></div>')

    fetched = d["fetched_at"].strftime("%Y-%m-%d %H:%M")

    body.append(
        f'<div class="live-bar" data-quotes-live>'
        f'<span class="live-dot"></span>'
        f'<span class="quote-status" id="quote-status">建置快照 {esc(fetched)}</span>'
        f'</div>'
        + callout(
            f'頁面載入後會透過 <code>/api/quotes</code> 代理更新報價：美股與'
            f'新興市場的個股與 ETF 每 45 秒，取自 Finnhub（免費層 60 次/分，'
            f'頁面上有四十幾檔，45 秒是不超額的最短間隔）。'
            f'<strong>收盤後會自動放慢</strong>——連兩輪報價都沒變化就把間隔'
            f'加倍（最慢 5 分鐘），一偵測到變化立刻恢復。<br>'
            f'<strong>原始指數（^GSPC、^KS11 等）維持建置快照</strong>'
            f'——報價 API 的免費層不含指數，所以本站另列一組追蹤同標的的'
            f'大盤 ETF，那一組才是會跳動的。<br>'
            f'沒有代理的環境（例如本機以 http.server 預覽）會安靜降級成'
            f'建置快照，狀態列的燈號會轉灰並註明。'
            f'　<a href="/tw/">台股報價已獨立成頁 →</a>'))

    # ================================================================ 美股 ==
    us = d["us"]
    if us["indices"]:
        tiles = [
            stat(r["name"], fmt(r["price"], 2),
                 delta=f'{fmt(r["change"], 2, signed=True)}　'
                       f'{fmt(r["change_percent"], 2, suffix="%", signed=True)}',
                 direction=None,
                 asof=f'昨收 {fmt(r["previous_close"], 2)}')
            for r in us["indices"][:6]
        ]
        earnings_html = ""
        if us.get("earnings"):
            chips = "".join(
                f'<span class="chip">{esc(e["symbol"])}'
                f'<strong style="margin-left:4px">{esc(e["date"][5:].replace("-", "/"))}'
                f'{("　" + esc(e["hour"])) if e["hour"] else ""}</strong></span>'
                for e in us["earnings"][:8])
            earnings_html = (f'<div class="chips" style="margin-top:12px">'
                             f'<span class="chip" style="font-weight:600">即將公布財報</span>'
                             f'{chips}</div>')
        body.append(section(
            "us", "美股",
            _status_note(us["status"], "Fincept Terminal")
            + f'<div class="grid grid-3">{"".join(tiles)}</div>'
            + earnings_html,
            note=f'報價時間 {_stamp(us["indices"])}',
            terms=["drawdown", "vix"]))

    body.append(section(
        "us-watchlist", "自選清單", _watchlist("us"),
        note="即時更新跟其他表格同節奏（45 秒）；清單只存在瀏覽器本機"))

    if us.get("proxies"):
        body.append(section(
            "us-etf", "大盤 ETF",
            _quote_table(us["proxies"])
            + callout("原始指數（^GSPC 等）在報價 API 的免費層不開放，這幾檔 ETF "
                      "追蹤相同標的且開放存取——所以<strong>它們是會即時更新的那一組</strong>，"
                      "上面的指數欄位則維持建置快照。"),
            note="每 45 秒更新（Finnhub 免費層額度上限）"))

    if us["stocks"]:
        body.append(section(
            "us-stocks", "美股權值股",
            _quote_table(us["stocks"])
            + _breadth_line(us["breadth"], "十檔權值股")
            + _movers_chart(us["stocks"], "權值股漲跌幅"),
            note=f'報價時間 {_stamp(us["stocks"])}'))

    if us["sectors"]:
        body.append(section(
            "us-sectors", "美股類股輪動",
            _quote_table(us["sectors"])
            + _breadth_line(us["sector_breadth"], "八大類股")
            + _movers_chart(us["sectors"], "類股 ETF 漲跌幅",
                            "類股間的差距比大盤本身更能看出資金在想什麼"),
            note="以 SPDR 類股 ETF 代表"))

    # ========================================================== 新興市場 ==
    em = d["em"]
    if em["indices"]:
        body.append(section(
            "em", "其他新興市場指數",
            _status_note(em["status"], "Fincept Terminal")
            + _quote_table(em["indices"])
            + _breadth_line(em["breadth"], "各國指數")
            + _movers_chart(em["indices"], "各國指數漲跌幅",
                            "同一天各國方向不一致時，多半是本地因素而非全球因素在主導"),
            note=f'報價時間 {_stamp(em["indices"])}',
            terms=["policy_divergence", "dollar_index"]))

    if em["etfs"]:
        body.append(section(
            "em-etfs", "新興市場 ETF（美元計價）",
            _quote_table(em["etfs"])
            + callout("以美元計價的 ETF 同時含匯率效果。當地指數漲但 ETF 跌，"
                      "代表那個國家的貨幣正在貶值——這是美元強弱對新興市場"
                      "最直接的傳導管道。<br><br>"
                      "中國以 FXI 與 ASHR 兩檔 ETF 代表：上證與深證指數在這個"
                      "資料來源取不到，本站不以其他指數替代充數。"),
            terms=["dollar_index"]))

    return "".join(body)


def render_tw(ctx: dict) -> str:
    d = ctx.get("equities") or {}
    body = []

    if not d.get("available"):
        return ('<div class="card"><p class="muted">'
                '報價來源目前不可用，請稍後重新建置。</p></div>')

    fetched = d["fetched_at"].strftime("%Y-%m-%d %H:%M")
    body.append(
        f'<div class="live-bar" data-quotes-live>'
        f'<span class="live-dot"></span>'
        f'<span class="quote-status" id="quote-status">建置快照 {esc(fetched)}</span>'
        f'</div>'
        + callout(
            f'頁面載入後每 <strong>5 秒</strong>透過 <code>/api/quotes</code> 代理'
            f'向證交所更新報價（含加權與櫃買指數）——5 秒是證交所對外發布'
            f'行情快照的節奏，這已是公開資料的即時上限，真正的逐筆行情要'
            f'付費資訊源。<strong>收盤後自動放慢</strong>（最慢 90 秒），'
            f'開盤偵測到變化立刻恢復。<br>'
            f'沒有代理的環境（例如本機以 http.server 預覽）會安靜降級成'
            f'建置快照，狀態列的燈號會轉灰並註明。'
            f'　<a href="/equities/">美股與其他市場 →</a>'))

    tw = d["tw"]
    if tw["index"] or tw["stocks"]:
        tiles = []
        for r in tw["index"]:
            symbol = str(r["symbol"])
            tiles.append(stat(
                r["name"],
                _live(symbol, "price", "tw", 2, fmt(r["price"], 2)),
                delta=_live(symbol, "change", "tw", 2,
                            fmt(r["change"], 2, signed=True))
                      + "　"
                      + _live(symbol, "change_percent", "tw", 2,
                              fmt(r["change_percent"], 2, suffix="%", signed=True)),
                asof=f'昨收 {fmt(r["previous_close"], 2)}'))
        fx = tw.get("usdtwd")
        if fx:
            tiles.append(stat(
                "美元兌台幣", fmt(fx["value"], 2),
                delta=f'近三月 {fmt(fx["chg_3m"], 1, suffix="%", signed=True)}',
                direction=None,
                asof=f'{zh_date(fx["as_of"], freq="d")} 資料　FRED 日頻'))
        for r in tw["stocks"][:3]:
            symbol = str(r["symbol"])
            tiles.append(stat(
                r["name"],
                _live(symbol, "price", "tw", 2, fmt(r["price"], 2)),
                delta=_live(symbol, "change", "tw", 2,
                            fmt(r["change"], 2, signed=True))
                      + "　"
                      + _live(symbol, "change_percent", "tw", 2,
                              fmt(r["change_percent"], 2, suffix="%", signed=True)),
                asof=f'{esc(symbol)}　昨收 {fmt(r["previous_close"], 2)}'))
        body.append(section(
            "tw", "大盤指數與權值股",
            _status_note(tw["status"], "證交所 mis.twse.com.tw（指數與個股同源）")
            + f'<div class="grid grid-4">{"".join(tiles)}</div>',
            note=f'報價時間 {_stamp(tw["stocks"] or tw["index"])}'))

    body.append(section(
        "tw-watchlist", "自選清單", _watchlist("tw"),
        note="含上櫃，跟其他台股表格同節奏（5 秒）即時更新；清單只存在瀏覽器本機"))

    trend = tw.get("trend") or {}
    if trend.get("index"):
        body.append(section(
            "tw-trend", "大盤走勢與成交量",
            line_chart("加權指數（收盤）",
                       [(trend["index"], "加權指數", "series-1")],
                       years=None, default_years=1, freq="d", digits=0,
                       with_table=False)
            + line_chart("每日成交金額",
                         [(trend["turnover"], "成交金額", "series-4")],
                         years=None, default_years=1, freq="d", digits=0,
                         suffix=" 億", chart_type="bar", height=180,
                         include_zero=True, with_table=False)
            + callout("量是價的體檢：指數創高而量能萎縮，漲勢的參與度在下降；"
                      "下跌爆量則常是恐慌或換手。兩張圖同一時間軸，上下對照看。"),
            note="近六個月日資料，證交所每日市場成交資訊"))

    if tw["stocks"]:
        body.append(section(
            "tw-stocks", "台股權值股",
            _quote_table(tw["stocks"], with_limits=True, market="tw")
            + _breadth_line(tw["breadth"], "八檔權值股")
            + _movers_chart(tw["stocks"], "台股權值股漲跌幅"),
            note="含漲跌停價；資料為證交所官方報價"))

    if tw.get("groups"):
        body.append(section(
            "tw-heat", "台股族群熱力圖",
            _heatmap(tw["groups"])
            + callout("顏色沿用全站慣例：<strong>綠漲紅跌</strong>（跟台灣看盤軟體"
                      "的紅漲綠跌相反），深淺代表幅度，±3% 封頂。族群右上角是"
                      "族群內的平均漲跌幅。磁磚跟著台股報價每 5 秒重刷。"),
            note="每族群取市值與成交量具代表性的個股"))

    if tw.get("ai"):
        body.append(section(
            "tw-ai", "AI 供應鏈熱力圖",
            _heatmap(tw["ai"])
            + callout("上中下游一條龍：<strong>上游</strong>晶片與先進封裝 → "
                      "<strong>中游</strong>散熱、電源、連接線纜、載板、機殼導軌 → "
                      "<strong>下游</strong>伺服器組裝與網通。這一張看的是 AI 資本"
                      "支出流到台灣的路徑：上游漲、中游跌，跟整條鏈齊漲，反映的"
                      "是完全不同的訂單預期。半導體製程環節的細部拆解見下方"
                      "「半導體產業鏈」。"),
            note="與其他熱力圖共用報價，不增加 API 用量", sub=True))

    if tw.get("semi"):
        body.append(section(
            "tw-semi", "半導體產業鏈熱力圖",
            _heatmap(tw["semi"])
            + callout("依製程順序排：設計 → 代工 → 記憶體 → 封測 → 設備 → 材料 → "
                      "載板 → 通路。同一天各環節的<strong>分歧</strong>比大盤漲跌"
                      "本身更有資訊量——設計漲、封測跌，跟整條鏈齊漲，是兩種"
                      "完全不同的行情。"),
            note="含上櫃（世界先進、群聯、環球晶、頎邦等），同走證交所 MIS",
            sub=True))

    if tw["etfs"]:
        body.append(section(
            "tw-etfs", "台股主要 ETF",
            _quote_table(tw["etfs"], with_limits=True, market="tw"),
            note="市值型、高股息型與大盤型"))

    wide = tw.get("wide_breadth") or {}
    if wide and tw.get("group_avgs"):
        avgs = tw["group_avgs"]
        body.append(section(
            "tw-breadth", "台股市場寬度",
            f'<div class="grid grid-4">'
            + stat("上漲", f'{wide["up"]} 檔', direction=None,
                   asof=f'追蹤宇宙 {wide["n"]} 檔')
            + stat("下跌", f'{wide["down"]} 檔', direction=None,
                   asof=f'持平 {wide["flat"]} 檔')
            + stat("平均漲跌", fmt(wide["average"], 2, suffix="%", signed=True))
            + stat("最強族群", esc(avgs[0]["name"]),
                   delta=fmt(avgs[0]["value"], 2, suffix="%", signed=True),
                   asof=f'最弱：{esc(avgs[-1]["name"])} '
                        f'{fmt(avgs[-1]["value"], 2, suffix="%", signed=True)}')
            + "</div>"
            + hbar_chart("族群平均漲跌幅", avgs, suffix="%", digits=2,
                         label_width=150, sub="由強到弱；顏色只標漲跌")
            + callout("樣本是本站追蹤的一百多檔族群代表股，不是全市場統計。"
                      "指數漲但下跌家數多，代表漲勢集中在少數權值股——"
                      "這種分歧比指數本身更值得注意。"),
            note="建置快照統計，非即時"))

    inst = tw.get("institutional") or {}
    marg = tw.get("margin") or {}
    if inst or marg:
        tiles = []
        if inst:
            tiles += [
                stat("外資買賣超", fmt(inst["foreign"], 1, suffix=" 億", signed=True),
                     asof=f'{esc(inst["date"])} 收盤後'),
                stat("投信買賣超", fmt(inst["trust"], 1, suffix=" 億", signed=True),
                     direction=None),
                stat("自營商買賣超", fmt(inst["dealer"], 1, suffix=" 億", signed=True),
                     direction=None, asof="自行買賣＋避險"),
            ]
        if marg:
            tiles.append(
                stat("融資餘額", fmt(marg["financing_yi"], 0, suffix=" 億"),
                     delta=f'較前日 {fmt(marg["financing_chg_yi"], 1, suffix=" 億", signed=True)}',
                     asof=f'融券 {fmt(marg["short_units"], 0)} 張'
                          f'（{fmt(marg["short_chg_units"], 0, signed=True)}）'))
        flows = tw.get("flows") or {}
        flow_chart = ""
        if flows.get("foreign_series"):
            s20 = flows.get("sum20") or {}
            flow_chart = (
                line_chart("外資每日買賣超",
                           [(flows["foreign_series"], "外資買賣超", None)],
                           years=None, default_years=1, freq="d", digits=0,
                           suffix=" 億", chart_type="bar", height=200,
                           include_zero=True, with_table=False,
                           sign_colors=("delta-up", "critical"))
                + f'<div class="grid grid-3">'
                + stat(f'外資近 {s20.get("days", 20)} 日累計',
                       fmt(s20.get("foreign"), 0, suffix=" 億", signed=True))
                + stat("投信累計", fmt(s20.get("trust"), 0, suffix=" 億", signed=True),
                       direction=None)
                + stat("自營商累計", fmt(s20.get("dealer"), 0, suffix=" 億", signed=True),
                       direction=None)
                + "</div>")
        body.append(section(
            "tw-flows", "三大法人資金流向與融資融券",
            f'<div class="grid grid-4">{"".join(tiles)}</div>'
            + flow_chart
            + callout("外資買賣超是台股最重要的資金流向指標——柱狀圖看的是"
                      "「連續性」：連買連賣的天數與力道，比單日金額更有意義。"
                      "投信買超常反映投顧作帳與 ETF 申購，自營商多為避險部位。<br>"
                      "融資餘額大增代表散戶槓桿在堆積，回檔時的賣壓也跟著變大。"
                      "<strong>大盤融資維持率沒有放</strong>：整戶擔保維持率需要"
                      "擔保品市值，證交所並未公開，市面上看到的數字都是券商或"
                      "資料商自己算的。這裡放的是公開資料裡最接近的原料——"
                      "融資餘額與其增減。"),
            note="證交所公開統計，每個交易日收盤後更新；歷史約三個月"))

    return "".join(body)
