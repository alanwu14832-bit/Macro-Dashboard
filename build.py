#!/usr/bin/env python3
"""建置整個網站。

    python3 build.py              # 一般建置（6 小時內的快取直接用）
    python3 build.py --fresh      # 忽略快取，全部重抓
    python3 build.py --offline    # 只用快取，不連網（快取無限期有效）
    python3 build.py --no-archive # 不寫入當天存檔

產出在 site/，是純靜態檔案，可直接部署到 Netlify 或用任何靜態伺服器開。
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import date, datetime

from macro import archive, data, paths
from macro.compute import (commodities, debt, equities, freshness, growth,
                           inflation, labor, market, news, rates, scenario,
                           signals, world)
from macro.render import layout
from macro.render.pages import (archive as archive_page,
                                commodities as commodities_page,
                                debt as debt_page,
                                equities as equities_page,
                                freshness as freshness_page,
                                fed as fed_page, growth as growth_page,
                                inflation as inflation_page, labor as labor_page,
                                market as market_page, news as news_page,
                                overview,
                                scenario as scenario_page, world as world_page)

MODULES = [
    ("labor", labor), ("inflation", inflation), ("rates", rates),
    ("debt", debt), ("growth", growth), ("market", market), ("world", world),
    ("commodities", commodities), ("equities", equities),
    ("news", news), ("freshness", freshness),
]


def taipei_stamp() -> str:
    return "最後更新 " + datetime.now().strftime("%Y-%m-%d %H:%M")


def main() -> int:
    parser = argparse.ArgumentParser(description="建置總經儀表板")
    parser.add_argument("--fresh", action="store_true", help="忽略快取，全部重抓")
    parser.add_argument("--offline", action="store_true", help="只用快取，不連網")
    parser.add_argument("--no-archive", action="store_true", help="不寫入當天存檔")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    started = time.time()
    ttl = 0 if args.fresh else (float("inf") if args.offline else 6 * 3600)
    verbose = not args.quiet
    # 新聞平常走自己的短 TTL，只有使用者明講要全抓或全離線時才跟著全站走。
    if args.fresh or args.offline:
        news.TTL_OVERRIDE = ttl

    print("== 1/5 載入資料 ==", flush=True)
    bundle = data.load(verbose=verbose, ttl=ttl)
    print(f"   {len(bundle.series)} 檔序列，缺漏 {len(bundle.missing)} 檔", flush=True)

    print("== 2/5 計算 ==", flush=True)
    ctx: dict = {}
    failures: list[str] = []
    for name, module in MODULES:
        try:
            ctx[name] = module.compute(bundle)
            if verbose:
                print(f"   ✓ {name}", flush=True)
        except Exception:
            failures.append(name)
            ctx[name] = {}
            print(f"   ✗ {name}", flush=True)
            traceback.print_exc()

    print("== 3/5 規則引擎與情境 ==", flush=True)
    found = signals.evaluate(ctx)
    summary = signals.summarise(found)
    scenario_data = scenario.compute(ctx["labor"], ctx["inflation"], ctx["rates"],
                                     ctx["debt"], ctx["growth"], summary)
    print(f"   訊號 {summary['total']} 條（{summary['tilt']}）→ "
          f"{scenario_data['name']}／{scenario_data['regime_label']}", flush=True)

    print("== 4/5 存檔與比對 ==", flush=True)
    snapshot = archive.build_snapshot(ctx, found, summary, scenario_data)
    prior = archive.previous()
    diff = signals.diff(found, (prior or {}).get("signals"))
    reading_changes = archive.reading_changes(snapshot, prior)
    if not args.no_archive:
        archive.save(snapshot)
    snapshots = archive.load_all()
    print(f"   存檔共 {len(snapshots)} 筆"
          f"{'；與上期相同' if diff.get('same') else ''}", flush=True)

    print("== 5/5 產生頁面 ==", flush=True)
    updated = taipei_stamp()
    pages = [
        ("/", "總覽", "美國總經儀表板",
         "把勞動、通膨、利率、債務、成長、全球與市場七個面向，收斂成一個可追蹤的判斷。",
         lambda: overview.render(ctx, found, summary, scenario_data, diff,
                                 reading_changes, updated)),
        ("/labor/", "勞動市場", "勞動市場",
         "損益兩平、初值修正追蹤、行業別拆解與綜合強弱指數。",
         lambda: labor_page.render(ctx, found)),
        ("/inflation/", "通膨", "通膨",
         "分項貢獻、漲勢廣度、住房落後、能源與薪資傳導。",
         lambda: inflation_page.render(ctx, found)),
        ("/fed/", "聯準會與利率", "聯準會與利率",
         "政策立場、完整殖利率曲線、長端拆解與信用利差。",
         lambda: fed_page.render(ctx, found)),
        ("/debt/", "長端與債務", "長端與債務",
         "r−g 債務動態、利息負擔、買盤結構與長端供給壓力。",
         lambda: debt_page.render(ctx, found)),
        ("/growth/", "成長與信用", "成長與信用",
         "消費、住宅、放款標準、違約率與衰退風險刻度。",
         lambda: growth_page.render(ctx, found)),
        ("/global/", "全球對照", "全球對照",
         "主要經濟體的通膨、失業、利率與匯率，每格標明資料日期。",
         lambda: world_page.render(ctx)),
        ("/news/", "國際新聞", "國際新聞",
         "多家獨立媒體同時報導的事件，來源目錄取自 WorldMonitor。",
         lambda: news_page.render(ctx)),
        ("/commodities/", "大宗商品", "大宗商品",
         "貴金屬、能源、工業金屬、農產，以及銅金比與金銀比這些總經讀數。",
         lambda: commodities_page.render(ctx)),
        ("/equities/", "股市報價", "股市報價",
         "美股、台股與其他新興市場的指數與個股報價，建置時取得的快照。",
         lambda: equities_page.render(ctx)),
        ("/market/", "市場面", "市場面",
         "股債相關性、波動率定位與實質利率張力——總經判斷被定價了多少。",
         lambda: market_page.render(ctx, found)),
        ("/scenario/", "情境與部位", "情境與部位",
         "九宮格定位、三種政策重心、轉換門檻與部位對照。",
         lambda: scenario_page.render(ctx, scenario_data, summary)),
        ("/freshness/", "資料新鮮度", "資料新鮮度",
         "每個指標多新、下次什麼時候更新，以及為什麼總經資料沒有即時可言。",
         lambda: freshness_page.render(ctx)),
        ("/archive/", "存檔", "存檔",
         "每天的判斷與關鍵讀數，可回看任一天的結論。",
         lambda: archive_page.render(snapshots)),
    ]

    written = []
    for path, title, heading, lede, render_fn in pages:
        try:
            body = render_fn()
        except Exception:
            print(f"   ✗ {path}", flush=True)
            traceback.print_exc()
            failures.append(path)
            continue
        html = layout.page(title=title, path=path, body=body, heading=heading,
                           lede=lede, updated=updated, description=lede)
        target = layout.write_page(path, html)
        written.append(target)
        if verbose:
            print(f"   ✓ {path}", flush=True)

    layout.copy_static()

    elapsed = time.time() - started
    print(f"\n完成：{len(written)} 頁，耗時 {elapsed:.1f} 秒 → {paths.SITE_DIR}")
    if bundle.missing:
        print(f"缺漏序列：{', '.join(bundle.missing)}")
    if failures:
        print(f"失敗：{', '.join(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
