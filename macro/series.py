"""A minimal time-series container and the transforms the dashboard needs.

Deliberately stdlib-only: a Series is an ordered list of (date, float) points
with no gaps-filling magic. Every transform returns a new Series so chains
stay readable, and every accessor tolerates missing data by returning None
rather than raising, because a build must not die when one release is late.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

Number = float | None


def _parse(d: str | date) -> date:
    return d if isinstance(d, date) else date.fromisoformat(d)


@dataclass(frozen=True)
class Series:
    series_id: str
    dates: list[date]
    values: list[float]
    label: str = ""
    unit: str = ""
    frequency: str = ""          # "d" | "w" | "m" | "q" | "a"
    source: str = ""
    meta: dict = field(default_factory=dict)

    # ---------- construction ----------
    @classmethod
    def from_pairs(cls, series_id: str, pairs, **kwargs) -> "Series":
        clean = [(_parse(d), float(v)) for d, v in pairs
                 if v is not None and v == v and str(v) not in (".", "", "NaN")]
        clean.sort(key=lambda p: p[0])
        return cls(series_id, [p[0] for p in clean], [p[1] for p in clean], **kwargs)

    def relabel(self, **kwargs) -> "Series":
        return replace(self, **kwargs)

    # ---------- basics ----------
    def __len__(self) -> int:
        return len(self.values)

    def __bool__(self) -> bool:
        return bool(self.values)

    @property
    def last(self) -> Number:
        return self.values[-1] if self.values else None

    @property
    def last_date(self) -> date | None:
        return self.dates[-1] if self.dates else None

    @property
    def first_date(self) -> date | None:
        return self.dates[0] if self.dates else None

    def at(self, index: int) -> Number:
        """Negative-index access that returns None instead of raising."""
        try:
            return self.values[index]
        except IndexError:
            return None

    def date_at(self, index: int) -> date | None:
        try:
            return self.dates[index]
        except IndexError:
            return None

    def value_on(self, when: date | str) -> Number:
        """Most recent observation at or before `when`."""
        when = _parse(when)
        found = None
        for d, v in zip(self.dates, self.values):
            if d <= when:
                found = v
            else:
                break
        return found

    def pairs(self) -> list[tuple[date, float]]:
        return list(zip(self.dates, self.values))

    # ---------- slicing ----------
    def tail(self, n: int) -> "Series":
        if n <= 0 or n >= len(self.values):
            return self
        return replace(self, dates=self.dates[-n:], values=self.values[-n:])

    def since(self, when: date | str) -> "Series":
        when = _parse(when)
        keep = [i for i, d in enumerate(self.dates) if d >= when]
        if not keep:
            return replace(self, dates=[], values=[])
        start = keep[0]
        return replace(self, dates=self.dates[start:], values=self.values[start:])

    def last_years(self, years: float) -> "Series":
        if not self.dates:
            return self
        cutoff = self.dates[-1] - timedelta(days=int(365.25 * years))
        return self.since(cutoff)

    def drop_last(self, n: int = 1) -> "Series":
        if n <= 0:
            return self
        return replace(self, dates=self.dates[:-n], values=self.values[:-n])

    # ---------- transforms ----------
    def _derive(self, dates, values, suffix, **kwargs) -> "Series":
        return Series(self.series_id + suffix, dates, values,
                      label=kwargs.pop("label", self.label),
                      unit=kwargs.pop("unit", self.unit),
                      frequency=self.frequency, source=self.source,
                      meta=dict(self.meta))

    def diff_months(self, months: int) -> "Series":
        """Level change over a calendar window, for monthly/quarterly series.

        跟 yoy() 同一個理由：diff(12) 是「往回數 12 筆」，序列缺格時
        窗會被拉長。要「跟 12 個月前比」就得對日曆，找不到基期就留白。
        """
        by_month = {(d.year, d.month): v for d, v in zip(self.dates, self.values)}
        d_out, v_out = [], []
        for d, v in zip(self.dates, self.values):
            year, month = d.year, d.month - months
            while month <= 0:
                month += 12
                year -= 1
            base = by_month.get((year, month))
            if base is None:
                continue
            d_out.append(d)
            v_out.append(v - base)
        return self._derive(d_out, v_out, f".diff{months}m", unit="")

    def diff(self, periods: int = 1) -> "Series":
        d, v = [], []
        for i in range(periods, len(self.values)):
            d.append(self.dates[i])
            v.append(self.values[i] - self.values[i - periods])
        return self._derive(d, v, f".diff{periods}", unit="")

    def pct_change(self, periods: int = 1) -> "Series":
        d, v = [], []
        for i in range(periods, len(self.values)):
            base = self.values[i - periods]
            if base == 0:
                continue
            d.append(self.dates[i])
            v.append((self.values[i] / base - 1.0) * 100.0)
        return self._derive(d, v, f".pct{periods}", unit="%")

    def yoy(self) -> "Series":
        """Year-over-year percent change.

        Monthly/quarterly/annual series match on the calendar (same month one
        year earlier), not on position: 2025-10 的 CPI 因政府關門停發，FRED 的
        序列就是缺一格，「往回數 12 筆」會除到 13 個月前的基期，年增率整個
        偏高。找不到去年同月就跳過該點——留白比錯數字好。
        Daily/weekly series keep the positional approximation.
        """
        if self.frequency in ("m", "q", "a"):
            by_month = {(d.year, d.month): v
                        for d, v in zip(self.dates, self.values)}
            d_out, v_out = [], []
            for d, v in zip(self.dates, self.values):
                base = by_month.get((d.year - 1, d.month))
                if not base:
                    continue
                d_out.append(d)
                v_out.append((v / base - 1.0) * 100.0)
            return self._derive(d_out, v_out, ".yoy", unit="%")
        return self.pct_change(self._periods_per_year())

    def annualised(self, months: int) -> "Series":
        """Compound annualised rate over a trailing window, in percent.

        Monthly/quarterly series anchor the window on the calendar, same
        reason as yoy()：序列缺一格時「往回數 N 筆」的窗其實比 N 個月長，
        年化指數卻還是按 N 個月算，結果整段期間都偏高。
        """
        if self.frequency in ("m", "q"):
            by_month = {(d.year, d.month): v
                        for d, v in zip(self.dates, self.values)}
            d_out, v_out = [], []
            for d, v in zip(self.dates, self.values):
                year, month = d.year, d.month - months
                while month <= 0:
                    month += 12
                    year -= 1
                base = by_month.get((year, month))
                if not base or base <= 0:
                    continue
                d_out.append(d)
                v_out.append(((v / base) ** (12.0 / months) - 1.0) * 100.0)
            return self._derive(d_out, v_out, f".ann{months}m", unit="%")

        per_year = self._periods_per_year()
        periods = max(1, round(per_year * months / 12))
        d, v = [], []
        for i in range(periods, len(self.values)):
            base = self.values[i - periods]
            if base <= 0:
                continue
            ratio = self.values[i] / base
            d.append(self.dates[i])
            v.append((ratio ** (per_year / periods) - 1.0) * 100.0)
        return self._derive(d, v, f".ann{months}m", unit="%")

    def rolling_mean(self, window: int) -> "Series":
        d, v = [], []
        for i in range(window - 1, len(self.values)):
            chunk = self.values[i - window + 1:i + 1]
            d.append(self.dates[i])
            v.append(sum(chunk) / window)
        return self._derive(d, v, f".ma{window}")

    def rolling_sum(self, window: int) -> "Series":
        d, v = [], []
        for i in range(window - 1, len(self.values)):
            d.append(self.dates[i])
            v.append(sum(self.values[i - window + 1:i + 1]))
        return self._derive(d, v, f".sum{window}")

    def scale(self, factor: float) -> "Series":
        return self._derive(list(self.dates), [x * factor for x in self.values], ".scaled")

    def shift_level(self, offset: float) -> "Series":
        return self._derive(list(self.dates), [x + offset for x in self.values], ".shift")

    def to_monthly(self, how: str = "mean") -> "Series":
        """Collapse a daily/weekly series to month-end points."""
        buckets: dict[tuple[int, int], list[float]] = {}
        for d, v in zip(self.dates, self.values):
            buckets.setdefault((d.year, d.month), []).append(v)
        d, v = [], []
        for (year, month) in sorted(buckets):
            chunk = buckets[(year, month)]
            d.append(date(year, month, 1))
            v.append(chunk[-1] if how == "last" else sum(chunk) / len(chunk))
        return Series(self.series_id + ".m", d, v, label=self.label, unit=self.unit,
                      frequency="m", source=self.source, meta=dict(self.meta))

    def index_to(self, when: date | str, base: float = 100.0) -> "Series":
        anchor = self.value_on(when)
        if not anchor:
            return self
        return self._derive(list(self.dates),
                            [x / anchor * base for x in self.values], ".idx")

    # ---------- statistics ----------
    def mean(self) -> Number:
        return sum(self.values) / len(self.values) if self.values else None

    def stdev(self) -> Number:
        if len(self.values) < 2:
            return None
        mu = self.mean()
        return math.sqrt(sum((x - mu) ** 2 for x in self.values) / (len(self.values) - 1))

    def zscore(self, lookback_years: float = 10) -> Number:
        window = self.last_years(lookback_years)
        mu, sd = window.mean(), window.stdev()
        if mu is None or not sd:
            return None
        return (self.last - mu) / sd

    def percentile_rank(self, lookback_years: float = 10) -> Number:
        window = self.last_years(lookback_years)
        if len(window) < 5 or self.last is None:
            return None
        below = sum(1 for x in window.values if x <= self.last)
        return below / len(window) * 100.0

    def min_max(self) -> tuple[Number, Number]:
        if not self.values:
            return None, None
        return min(self.values), max(self.values)

    def change_over(self, periods: int) -> Number:
        prior = self.at(-1 - periods)
        if prior is None or self.last is None:
            return None
        return self.last - prior

    def _periods_per_year(self) -> int:
        return {"d": 252, "w": 52, "m": 12, "q": 4, "a": 1}.get(self.frequency, 12)


EMPTY = Series("", [], [])


def align(*series: Series) -> tuple[list[date], list[list[float]]]:
    """Inner-join several series on their common dates."""
    if not series or any(not s for s in series):
        return [], [[] for _ in series]
    common = set(series[0].dates)
    for s in series[1:]:
        common &= set(s.dates)
    dates = sorted(common)
    lookup = [dict(zip(s.dates, s.values)) for s in series]
    return dates, [[table[d] for d in dates] for table in lookup]


def correlation(a: Series, b: Series, lag: int = 0) -> Number:
    """Pearson correlation of `a` against `b` shifted forward by `lag` periods."""
    if lag:
        if lag >= len(b):
            return None
        b = Series(b.series_id, b.dates[:-lag] if lag > 0 else b.dates[-lag:],
                   b.values[lag:] if lag > 0 else b.values[:lag],
                   frequency=b.frequency)
    dates, cols = align(a, b)
    if len(dates) < 8:
        return None
    xs, ys = cols
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not dx or not dy:
        return None
    return num / (dx * dy)
