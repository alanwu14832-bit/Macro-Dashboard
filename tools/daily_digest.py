#!/usr/bin/env python3
"""每日排程要用的一次性摘要：把寫要聞需要的東西全部印出來。

    python3 tools/daily_digest.py

存在的理由是權限，不是功能。排程每天做的事一樣，但以前那幾段比對存檔、
抓首頁數字、拆新聞頁的分析都是當場寫的內嵌腳本，指令字串天天不同，
權限比對命中不了任何已核准的樣式，於是每跑一次就要按一輪核准。把它們
凍結成這支固定指令之後，整個排程的指令集就是不變的，核准一次就好。

一律離線（ttl=inf），只讀 build.py 已經抓好的快取與 data/archive/，
不連網、不寫檔。要在 build.py 跑完之後執行。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from macro import archive, data, paths
from macro.compute import (commodities, debt, equities, fedfunds, freshness,
                           growth, inflation, labor, market, news, rates,
                           scenario, signals, world)

MODULES = [
    ("labor", labor), ("inflation", inflation), ("rates", rates),
    ("fedfunds", fedfunds), ("debt", debt), ("growth", growth),
    ("market", market), ("world", world), ("commodities", commodities),
    ("equities", equities), ("news", news), ("freshness", freshness),
]

# 第 3 點「跟昨天比」要盯的讀數。archive.reading_changes 自己有一套，
# 這裡明列是為了讓輸出順序穩定、跟排程說明書上的清單對得起來。
WATCHED = [
    ("core_pce", "核心 PCE", "%"),
    ("core_cpi", "核心 CPI", "%"),
    ("supercore", "核心服務除住房", "%"),
    ("unemployment", "失業率", "%"),
    ("payrolls_3m", "三月均非農", "千人"),
    ("payrolls_latest", "最新非農", "千人"),
    ("breakeven", "損益兩平", "千人"),
    ("ten_year", "10 年期", "%"),
    ("real_ten_year", "10 年實質", "%"),
    ("curve_10_2", "10 減 2", "pp"),
    ("recession_gauge", "衰退風險刻度", ""),
    ("composite_labor", "勞動綜合強弱", ""),
]

RULE = "=" * 72


def num(v, digits=2):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return f"{v:,.{digits}f}"
    return str(v)


def pct(v, digits=1):
    return "—" if v is None else f"{v:+.{digits}f}%"


def scalars(obj, digits=3):
    """只留純量欄位。compute 出來的 dict 常常夾帶整條 Series，直接印會爆掉。"""
    if not isinstance(obj, dict):
        return "—"
    out = {}
    for k, v in obj.items():
        if isinstance(v, bool) or v is None or isinstance(v, str):
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = round(v, digits)
        elif isinstance(v, (date, datetime)):
            out[k] = str(v)
    return out or "—"


def head(title):
    print(f"\n{RULE}\n{title}\n{RULE}")


def sub(title):
    print(f"\n-- {title} " + "-" * max(0, 66 - len(title)))


def load_context():
    bundle = data.load(verbose=False, ttl=float("inf"))
    news.TTL_OVERRIDE = float("inf")
    ctx: dict = {"_bundle": bundle}
    for name, module in MODULES:
        try:
            ctx[name] = module.compute(bundle)
        except Exception as exc:  # 單一模組壞掉不該讓整份摘要消失
            ctx[name] = {}
            print(f"   ✗ {name} 計算失敗：{exc}", file=sys.stderr)
    return bundle, ctx


def section_scenario(ctx):
    found = signals.evaluate(ctx)
    summary = signals.summarise(found)
    sc = scenario.compute(ctx["labor"], ctx["inflation"], ctx["rates"],
                          ctx["debt"], ctx["growth"], summary)
    head("1. 情境判定與訊號")
    print(f"九宮格　　：{sc['name']}（就業 {sc['employment_label']} × "
          f"通膨 {sc['inflation_label']}）")
    print(f"政策重心　：{sc.get('regime_label') or sc.get('regime')}")
    print(f"長端供給　：{sc.get('supply_pressure')}　衰退刻度：{sc.get('recession_gauge')}")
    print(f"市場對照　：{sc.get('market_check')}")
    print(f"政策傾向　：{summary['tilt']}（score {summary['score']}）")
    print(f"訊號分布　：共 {summary['total']} 條／"
          f"偏升息 {summary['hawkish']}、偏降息 {summary['dovish']}、中性 {summary['neutral']}")

    sub("全部訊號（severity / direction / module）")
    for s in found:
        print(f"  [{s.get('severity','?'):<6}] [{s.get('direction','?'):<7}] "
              f"[{s.get('module','')}] {s.get('headline','')}")
        if s.get("evidence"):
            print(f"           證據：{s['evidence']}")
    return found, summary, sc


def section_diff(found):
    head("2. 跟上一份存檔比對")
    arc_dir = paths.ARCHIVE_DIR
    snaps = sorted(f for f in os.listdir(arc_dir) if f.endswith(".json"))
    if len(snaps) < 2:
        print("存檔不足兩筆，無法比對。")
        return
    prev_f, curr_f = snaps[-2], snaps[-1]
    with open(os.path.join(arc_dir, prev_f), encoding="utf-8") as fh:
        prev = json.load(fh)
    with open(os.path.join(arc_dir, curr_f), encoding="utf-8") as fh:
        curr = json.load(fh)
    # generated_at 一定要印。同一天的存檔會被反覆覆寫（本機建置一次、雲端
    # 每小時一次），本機跑完 build.py 後手上的「昨天」可能是昨天中午的版本，
    # 而雲端的是昨天深夜的版本。拿錯版本比對，會把前天就發生的變化當成今天
    # 的新變化報出去——2026-09-12 這一輪就踩過一次。
    print(f"比對　　　：{prev['date']}（{prev.get('generated_at')}）"
          f" → {curr['date']}（{curr.get('generated_at')}）")
    print("　　　　　　若上一份的產生時間明顯早於當天收盤，代表它是當天的中途版本，"
          "先 git pull 取回雲端的最終版再比對。")

    pa = {s["key"]: s for s in prev.get("signals", [])}
    ca = {s["key"]: s for s in curr.get("signals", [])}
    added, gone = ca.keys() - pa.keys(), pa.keys() - ca.keys()

    sub("訊號增減")
    if not added and not gone:
        print("  與上一份相同，沒有新增或消失的訊號。")
    for k in sorted(added):
        s = ca[k]
        print(f"  ＋ [{s.get('direction')}] {s.get('headline')}")
        print(f"      {s.get('evidence','')}")
    for k in sorted(gone):
        s = pa[k]
        print(f"  － [{s.get('direction')}] {s.get('headline')}")
        print(f"      （上一份的證據：{s.get('evidence','')}）")

    sub("情境與摘要")
    ps, cs = prev.get("scenario", {}), curr.get("scenario", {})
    for field, label in [("name", "九宮格"), ("employment", "就業格"),
                         ("inflation", "通膨格"), ("regime", "政策重心"),
                         ("lean", "傾向")]:
        mark = "  " if ps.get(field) == cs.get(field) else "＊"
        arrow = "" if ps.get(field) == cs.get(field) else f"  ← 原為 {ps.get(field)}"
        print(f"  {mark} {label}：{cs.get(field)}{arrow}")
    psu, csu = prev.get("summary", {}), curr.get("summary", {})
    print(f"  {'  ' if psu.get('total') == csu.get('total') else '＊'} 訊號數："
          f"{csu.get('total')}（原 {psu.get('total')}）　"
          f"偏升息 {csu.get('hawkish')}（原 {psu.get('hawkish')}）／"
          f"偏降息 {csu.get('dovish')}（原 {psu.get('dovish')}）")

    sub("關鍵讀數")
    pr, cr = prev.get("readings", {}), curr.get("readings", {})
    for key, label, unit in WATCHED:
        a, b = pr.get(key), cr.get(key)
        if a is None and b is None:
            continue
        same = (a == b)
        mark = "  " if same else "＊"
        tail = "（同）" if same else f"　← 原 {num(a)}"
        print(f"  {mark} {label:<14}{num(b)} {unit}{tail}")


def section_readings(ctx):
    head("3. 關鍵讀數與政策定價")
    ff = ctx.get("fedfunds") or {}
    nxt = ff.get("next") or {}
    if nxt:
        probs = nxt.get("probs") or {}
        print(f"下次會議　：{nxt.get('label')}　{nxt.get('headline','')}")
        print(f"　　機率　：升息 {probs.get('hike25', 0) * 100:.0f}%"
              f"（+50bp {probs.get('hike50', 0) * 100:.0f}%）／"
              f"不變 {probs.get('hold', 0) * 100:.0f}%／"
              f"降息 {probs.get('cut25', 0) * 100:.0f}%")
    if ff.get("summary"):
        print(f"路徑　　　：{ff['summary']}")
    if ff.get("effr") is not None:
        print(f"EFFR　　　：{ff['effr']}%（{ff.get('effr_date')}）")

    rt = ctx.get("rates") or {}
    # 這些 dict 裡混著整條 Series 物件，只能正面表列純量，不能用
    # 「排除 list/dict」過濾——Series 兩者都不是，印出來是幾十萬字。
    print(f"政策立場　：{scalars(rt.get('stance'))}")
    print(f"長端拆解　：{scalars(rt.get('decomposition'))}")
    print(f"曲線形狀　：{scalars(rt.get('shape'))}")
    print(f"信用利差　：{scalars(rt.get('credit'))}")
    print(f"金融情勢　：{scalars(rt.get('conditions'))}")


def section_markets(ctx):
    head("4. 市場快照")
    cm = ctx.get("commodities") or {}

    sub("商品（值／近一月／近三月／近一年／十年百分位）")
    for group in cm.get("groups", []):
        print(f"  ［{group.get('title')}］")
        for r in group.get("rows", []):
            print(f"    {r.get('name',''):<14}{num(r.get('value'))} {r.get('unit',''):<10}"
                  f"{pct(r.get('chg_1m')):>9}{pct(r.get('chg_3m')):>9}"
                  f"{pct(r.get('chg_1y')):>9}　pct10y {num(r.get('pct10y'), 0)}")
    for r in (cm.get("precious") or {}).get("rows", []):
        print(f"    {r.get('name',''):<14}{num(r.get('value'))} {r.get('unit',''):<10}"
              f"{pct(r.get('chg_1m')):>9}{pct(r.get('chg_1y')):>9}"
              f"　ytd {pct(r.get('chg_ytd'))}　pct10y {num(r.get('pct10y'), 0)}")
    pm = cm.get("precious") or {}
    if pm.get("gold_silver_ratio") is not None:
        print(f"    金銀比 {num(pm['gold_silver_ratio'])}（十年均 {num(pm.get('gold_silver_avg10y'))}）")
    cg = cm.get("copper_gold") or {}
    if cg.get("ratio") is not None:
        print(f"    銅金比 {num(cg['ratio'], 4)}　十年百分位 {num(cg.get('pct10y'), 0)}　{cg.get('verdict','')}")

    mk = ctx.get("market") or {}
    sub("市場面")
    for r in (mk.get("equities") or {}).get("rows", []):
        print(f"    {r.get('name',''):<14}{num(r.get('value'))}"
              f"{pct(r.get('chg_1m')):>9}{pct(r.get('chg_ytd')):>9}"
              f"　距一年高點 {pct(r.get('from_high'))}")
    for r in (mk.get("crypto") or {}).get("rows", []):
        print(f"    {r.get('name',''):<14}{num(r.get('value'))}"
              f"{pct(r.get('chg_1m')):>9}{pct(r.get('chg_1y')):>9}")
    vol = mk.get("volatility") or {}
    if vol.get("vix") is not None:
        print(f"    VIX {num(vol['vix'])}　{vol.get('verdict','')}")
    risk = mk.get("risk") or {}
    if risk:
        print(f"    風險胃納 {num(risk.get('score'), 1)}　{risk.get('label','')}")
    sb = mk.get("stock_bond") or {}
    if sb.get("latest") is not None:
        print(f"    股債相關 {num(sb['latest'])}　{sb.get('verdict','')}")

    wd = (ctx.get("world") or {}).get("dollar") or {}
    if wd.get("broad") is not None:
        print(f"    美元指數（廣體）{num(wd['broad'])}　近一月 {pct(wd.get('chg_1m'))}"
              f"　近一年 {pct(wd.get('chg_1y'))}　（{wd.get('as_of')}）")

    eq = ctx.get("equities") or {}
    if eq.get("available"):
        sub(f"報價（{eq.get('source_note','')}　{eq.get('fetched_at')}）")
        for region, label in [("us", "美股"), ("tw", "台股")]:
            blk = eq.get(region) or {}
            rows = []
            idx = blk.get("index") or blk.get("indices") or []
            rows += list(idx if isinstance(idx, list) else [idx])
            rows += list(blk.get("stocks") or [])[:6]
            if not rows:
                continue
            status = (blk.get("status") or {})
            print(f"  ［{label}］{status if not isinstance(status, dict) else status.get('label', status)}")
            for r in rows:
                if not isinstance(r, dict):
                    continue
                print(f"    {str(r.get('name','')):<12}{num(r.get('price'))}"
                      f"　{num(r.get('change')):>10}　{pct(r.get('change_percent')):>8}"
                      f"　昨收 {num(r.get('previous_close'))}"
                      f"　{r.get('market_status','')}")


def section_news(ctx):
    nw = ctx.get("news") or {}
    head("5. 新聞")
    if not nw.get("available"):
        print("新聞模組不可用（頁面會自行降級）。")
        return
    st = nw.get("stats") or {}
    failed = st.get("feeds_failed", 0)
    print(f"來源　　　：嘗試 {st.get('feeds_tried')} 個，失敗 {failed} 個"
          f"{'　→ 超過 10 個，回報時要提' if failed > 10 else ''}")
    if st.get("failed_names"):
        print(f"　失敗清單：{', '.join(st['failed_names'])}")
    print(f"條目　　　：{st.get('items')} 則（{st.get('window_hours')} 小時內，已去重）"
          f"　交集事件 {st.get('clusters')} 件")

    sub("今日焦點（多家同報，依交集家數排序）")
    for c in nw.get("clusters", []):
        srcs = c.get("sources") or []
        print(f"  [{c.get('count')}家] {c.get('headline','')}")
        print(f"         來源：{', '.join(srcs)}　{c.get('latest')}")
        for other in (c.get("others") or [])[:2]:
            print(f"         另一種寫法：{other}")

    sub("與總經相關（標題命中本站在追的主題）")
    for it in nw.get("macro", []):
        print(f"  · [{it.get('category_label','')}／{it.get('source','')}] {it.get('title','')}")

    sub("依分類")
    for cat in nw.get("categories", []):
        print(f"  ［{cat.get('label')}］")
        for it in cat.get("items", []):
            print(f"    · [{it.get('source','')}] {it.get('title','')}")


def main() -> int:
    print(f"總經儀表板每日摘要　產生於 {datetime.now():%Y-%m-%d %H:%M}（台北）")
    bundle, ctx = load_context()
    print(f"序列 {len(bundle.series)} 檔，缺漏 {len(bundle.missing)} 檔"
          + (f"：{', '.join(sorted(bundle.missing))}" if bundle.missing else ""))
    found, summary, sc = section_scenario(ctx)
    section_diff(found)
    section_readings(ctx)
    section_markets(ctx)
    section_news(ctx)
    print(f"\n{RULE}\n摘要結束。接下來：寫 data/brief.json → "
          f"python3 build.py --offline --no-archive --quiet → commit & push\n{RULE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
