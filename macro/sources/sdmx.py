"""SDMX-JSON reader for the ECB Data Portal and OECD.

FRED's OECD-sourced international series are largely frozen (Japan CPI stops in
2021, China in 2025, Taiwan absent), so the global page reads the statistical
agencies directly. The two APIs speak different SDMX-JSON envelopes:

  ECB  (1.0): {"dataSets": [...], "structure":  {...}}
  OECD (2.0): {"data": {"dataSets": [...], "structures": [{...}]}}

`parse` normalises both, and `series_map` returns one Series per series key,
labelled by the dimension values that vary across the response.
"""
from __future__ import annotations

from ..http import get
from ..series import Series

ECB_BASE = "https://data-api.ecb.europa.eu/service/data"
OECD_BASE = "https://sdmx.oecd.org/public/rest/data"
EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"


def _structure(root: dict) -> dict:
    st = root.get("structures") or root.get("structure")
    if isinstance(st, list):
        st = st[0] if st else {}
    return st or {}


def parse(payload: dict) -> list[tuple[dict, list[tuple[str, float]]]]:
    """-> [(dimension_ids, [(period, value), ...]), ...]"""
    import json as _json
    if isinstance(payload, str):
        payload = _json.loads(payload)
    root = payload.get("data", payload)
    datasets = root.get("dataSets") or []
    if not datasets:
        return []
    structure = _structure(root)
    dims = structure.get("dimensions", {})
    series_dims = dims.get("series") or []
    obs_dims = dims.get("observation") or []
    periods = [v["id"] for v in (obs_dims[0]["values"] if obs_dims else [])]

    out = []
    series_blob = datasets[0].get("series") or {}
    for key, blob in series_blob.items():
        idx = [int(x) for x in key.split(":")]
        labels = {}
        for position, value_index in enumerate(idx):
            if position >= len(series_dims):
                continue
            values = series_dims[position].get("values") or []
            if value_index < len(values):
                labels[series_dims[position]["id"]] = values[value_index]["id"]
        points = []
        for pos, cell in blob.get("observations", {}).items():
            if not cell or cell[0] is None:
                continue
            i = int(pos)
            if i < len(periods):
                points.append((periods[i], float(cell[0])))
        points.sort()
        out.append((labels, points))

    # A flat (non-series) response puts observations straight on the dataset.
    if not out and datasets[0].get("observations"):
        points = [(periods[int(i)], float(c[0]))
                  for i, c in datasets[0]["observations"].items()
                  if c and c[0] is not None]
        points.sort()
        out.append(({}, points))
    return out


def _normalise_period(period: str) -> str:
    """SDMX periods: 2026-07, 2026-Q2, 2026, 2026-07-31 -> ISO date."""
    period = period.strip()
    if "Q" in period:
        year, quarter = period.split("-Q") if "-Q" in period else (period[:4], period[-1])
        return f"{year}-{(int(quarter) - 1) * 3 + 1:02d}-01"
    parts = period.split("-")
    if len(parts) == 1:
        return f"{parts[0]}-01-01"
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}-01"
    return period


def fetch(url: str, *, ttl: float = 12 * 3600) -> list[tuple[dict, list[tuple[str, float]]]]:
    try:
        return parse(get(url, ttl=ttl, namespace="sdmx", timeout=60))
    except Exception:
        return []


def one(url: str, *, series_id: str, label: str = "", unit: str = "",
        frequency: str = "m", source: str = "", ttl: float = 12 * 3600) -> Series:
    """Fetch a URL expected to return a single series."""
    blocks = fetch(url, ttl=ttl)
    if not blocks:
        return Series(series_id, [], [], label=label or series_id, unit=unit,
                      frequency=frequency, source=source)
    labels, points = blocks[0]
    return Series.from_pairs(series_id, [(_normalise_period(p), v) for p, v in points],
                             label=label or series_id, unit=unit, frequency=frequency,
                             source=source, meta={"dims": labels})


def by_area(url: str, *, dim: str = "REF_AREA", unit: str = "", frequency: str = "m",
            source: str = "OECD", ttl: float = 12 * 3600) -> dict[str, Series]:
    """Fetch a multi-country request and key the result by the area dimension.

    A country usually comes back as several series (different methodology,
    expenditure basket, adjustment). Keep the one that runs furthest forward,
    breaking ties on length — a discontinued vintage must never shadow the
    live one.
    """
    out: dict[str, Series] = {}
    for labels, points in fetch(url, ttl=ttl):
        area = labels.get(dim)
        if not area or not points:
            continue
        candidate = Series.from_pairs(
            f"{source}:{area}", [(_normalise_period(p), v) for p, v in points],
            label=area, unit=unit, frequency=frequency, source=source,
            meta={"dims": labels})
        current = out.get(area)
        if current is None or (candidate.last_date, len(candidate)) > (current.last_date, len(current)):
            out[area] = candidate
    return out


# ------------------------------------------------------------------ Eurostat -

def eurostat(dataset: str, params: dict, *, series_id: str, label: str = "",
             unit: str = "", frequency: str = "m", ttl: float = 12 * 3600) -> Series:
    """Eurostat uses JSON-stat, not SDMX-JSON."""
    from ..http import build_url, get_json
    query = dict(params)
    query["format"] = "JSON"
    try:
        payload = get_json(build_url(f"{EUROSTAT_BASE}/{dataset}", query),
                           ttl=ttl, namespace="sdmx", timeout=60)
    except Exception:
        return Series(series_id, [], [], label=label, unit=unit, frequency=frequency)
    values = payload.get("value") or {}
    time_dim = ((payload.get("dimension") or {}).get("time") or {})
    index = ((time_dim.get("category") or {}).get("index") or {})
    order = sorted(index.items(), key=lambda kv: kv[1])
    points = []
    for period, position in order:
        cell = values.get(str(position))
        if cell is None:
            continue
        points.append((_normalise_period(period), float(cell)))
    return Series.from_pairs(series_id, points, label=label or series_id, unit=unit,
                             frequency=frequency, source="Eurostat")
