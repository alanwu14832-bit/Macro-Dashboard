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
