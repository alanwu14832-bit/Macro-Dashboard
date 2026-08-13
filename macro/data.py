"""Load the catalogue into memory, recording what failed.

The bundle is a plain dict of series_id -> Series with a `.missing` list, so a
build can finish and report gaps rather than crashing on a renamed series.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import catalogue
from .series import Series, EMPTY
from .sources import fred


@dataclass
class Bundle:
    series: dict[str, Series] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    def __getitem__(self, series_id: str) -> Series:
        return self.series.get(series_id, EMPTY)

    def get(self, series_id: str) -> Series:
        return self.series.get(series_id, EMPTY)

    def has(self, series_id: str) -> bool:
        return bool(self.series.get(series_id))

    def add(self, series_id: str, s: Series) -> None:
        self.series[series_id] = s
        if not s:
            self.missing.append(series_id)


def load(groups: list[str] | None = None, *, verbose: bool = True,
         ttl: float = 6 * 3600) -> Bundle:
    bundle = Bundle()
    specs: dict[str, catalogue.Spec] = {}
    for name, group in catalogue.ALL_GROUPS.items():
        if groups and name not in groups:
            continue
        specs.update(group)
    specs.update(catalogue.sector_specs())

    total = len(specs)
    for i, (series_id, (label, unit, freq, start)) in enumerate(specs.items(), 1):
        s = fred.series(series_id, label=label, unit=unit, frequency=freq,
                        start=start, ttl=ttl)
        bundle.add(series_id, s)
        if verbose and (i % 25 == 0 or i == total):
            print(f"  資料載入 {i}/{total}", flush=True)
    if verbose and bundle.missing:
        print(f"  ⚠ 缺漏 {len(bundle.missing)} 檔：{', '.join(bundle.missing)}", flush=True)
    return bundle


def calendar_gaps(bundle: Bundle, *, window_years: float = 3.0) -> dict:
    """月頻序列近幾年的「內部缺格」——序列中間少掉的月份。

    位置型轉換（往回數 N 筆）遇到缺格會默默用錯基期，2025-10 政府關門
    停發 CPI 就讓年增率錯了 0.2 個百分點而沒有任何錯誤訊息。轉換層已改
    成日曆對齊，這裡是第二道防線：把缺格攤在建置紀錄上，讓「資料有洞」
    這件事永遠是看得見的，而不是等有人發現數字對不上才回頭找。

    回傳 {(year, month): [series_id, ...]}，只看每檔序列自己的頭尾之間，
    所以發布落後（尾端還沒到）不會被誤報。
    """
    gaps: dict[tuple[int, int], list[str]] = {}
    for series_id, s in bundle.series.items():
        if s.frequency != "m" or len(s) < 3:
            continue
        recent = s.last_years(window_years)
        if len(recent) < 3:
            continue
        have = {(d.year, d.month) for d in recent.dates}
        year, month = recent.dates[0].year, recent.dates[0].month
        end = (recent.dates[-1].year, recent.dates[-1].month)
        while (year, month) < end:
            month += 1
            if month > 12:
                month, year = 1, year + 1
            if (year, month) < end and (year, month) not in have:
                gaps.setdefault((year, month), []).append(series_id)
    return gaps
