"""股市報價頁：美股、台股、其他新興市場。"""
from __future__ import annotations

from ..common import hbar_chart
from ..html import (callout, delta_span, esc, fmt, section, stat, table)


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


def _status_note(status: str, source: str) -> str:
    return (f'<p class="muted" style="font-size:.83rem;margin:-4px 0 12px">'
            f'狀態：{esc(status)}　·　來源：{esc(source)}</p>')


def render(ctx: dict) -> str:
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
            f'頁面載入後會透過 <code>/api/quotes</code> 代理更新報價：'
            f'<strong>台股（含加權指數）每 5 秒</strong>，取自證交所——5 秒就是'
            f'證交所對外發布行情快照的節奏，這已是它公開資料的即時上限；'
            f'美股與新興市場的個股與 ETF 每 45 秒，取自 Finnhub（免費層 60 次/分，'
            f'頁面上有四十幾檔，45 秒是不超額的最短間隔）。'
            f'上方狀態列會顯示實際的更新時間與來源。<br>'
            f'<strong>美股與新興市場的原始指數（^GSPC、^KS11 等）維持建置快照</strong>'
            f'——報價 API 的免費層不含指數，所以本站另列一組追蹤同標的的大盤 ETF，'
            f'那一組才是會跳動的。台股加權指數不受此限，證交所直接提供。<br>'
            f'沒有代理的環境（例如本機以 http.server 預覽）會安靜降級成建置快照，'
            f'狀態列的燈號會轉灰並註明。'
            f'　<a href="/freshness/">看更新時程 →</a>'))

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
        body.append(section(
            "us", "美股",
            _status_note(us["status"], "Fincept Terminal")
            + f'<div class="grid grid-3">{"".join(tiles)}</div>',
            note=f'報價時間 {_stamp(us["indices"])}',
            terms=["drawdown", "vix"]))

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

    # ================================================================ 台股 ==
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
            "tw", "台灣股市",
            _status_note(tw["status"], "證交所 mis.twse.com.tw（指數與個股同源）")
            + f'<div class="grid grid-4">{"".join(tiles)}</div>',
            note=f'報價時間 {_stamp(tw["stocks"] or tw["index"])}'))

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

    if tw.get("semi"):
        body.append(section(
            "tw-semi", "半導體產業鏈熱力圖",
            _heatmap(tw["semi"])
            + callout("依製程順序排：設計 → 代工 → 記憶體 → 封測 → 設備 → 材料 → "
                      "載板 → 通路。同一天各環節的<strong>分歧</strong>比大盤漲跌"
                      "本身更有資訊量——設計漲、封測跌，跟整條鏈齊漲，是兩種"
                      "完全不同的行情。"),
            note="含上櫃（世界先進、群聯、環球晶、頎邦等），同走證交所 MIS"))

    if tw["etfs"]:
        body.append(section(
            "tw-etfs", "台股主要 ETF",
            _quote_table(tw["etfs"], with_limits=True, market="tw"),
            note="市值型、高股息型與大盤型"))

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
