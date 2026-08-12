"""FRED client.

Reads the API key from ~/.config/fincept/keys.json (where the fincept MCP
already keeps it) or the FRED_API_KEY environment variable. Everything goes
through macro.http, so repeated builds hit disk rather than the API.
"""
from __future__ import annotations

import json
import os

from ..http import build_url, get_json, FetchError
from ..series import Series

BASE = "https://api.stlouisfed.org/fred"
_KEY_CACHE: str | None = None

# FRED frequency codes -> our short codes
_FREQ = {"Daily": "d", "Weekly": "w", "Biweekly": "w", "Monthly": "m",
         "Quarterly": "q", "Semiannual": "q", "Annual": "a",
         "Daily, Close": "d", "Daily, 7-Day": "d"}


def api_key() -> str:
    global _KEY_CACHE
    if _KEY_CACHE:
        return _KEY_CACHE
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        path = os.path.expanduser("~/.config/fincept/keys.json")
        if os.path.exists(path):
            with open(path) as fh:
                key = (json.load(fh).get("FRED_API_KEY") or "").strip()
    if not key:
        raise FetchError("No FRED API key found (FRED_API_KEY or "
                         "~/.config/fincept/keys.json)")
    _KEY_CACHE = key
    return key


def observations(series_id: str, *, start: str = "1990-01-01",
                 units: str | None = None, frequency: str | None = None,
                 aggregation: str | None = None, ttl: float = 6 * 3600,
                 realtime: tuple[str, str] | None = None) -> list[tuple[str, str]]:
    """Raw (date, value) strings for one series.

    `realtime` pins the vintage, which is how the revision tracker asks FRED
    "what did this series look like as of that day?".
    """
    params = {
        "series_id": series_id, "api_key": api_key(), "file_type": "json",
        "observation_start": start, "units": units, "frequency": frequency,
        "aggregation_method": aggregation,
    }
    if realtime:
        params["realtime_start"], params["realtime_end"] = realtime
        ttl = 30 * 24 * 3600  # a fixed vintage never changes
    payload = get_json(build_url(f"{BASE}/series/observations", params),
                       ttl=ttl, namespace="fred")
    return [(o["date"], o["value"]) for o in payload.get("observations", [])
            if o.get("value") not in (".", None, "")]


def metadata(series_id: str, ttl: float = 30 * 24 * 3600) -> dict:
    params = {"series_id": series_id, "api_key": api_key(), "file_type": "json"}
    payload = get_json(build_url(f"{BASE}/series", params), ttl=ttl, namespace="fred")
    rows = payload.get("seriess") or []
    return rows[0] if rows else {}


def series(series_id: str, *, label: str = "", start: str = "1990-01-01",
           unit: str = "", frequency: str = "", with_meta: bool = False,
           **kwargs) -> Series:
    """Fetch one series, returning an empty Series if the source fails.

    A late or renamed release must degrade one panel, not the whole build.
    """
    try:
        rows = observations(series_id, start=start, **kwargs)
    except Exception:
        return Series(series_id, [], [], label=label or series_id, unit=unit,
                      frequency=frequency, source="FRED",
                      meta={"error": "fetch-failed"})
    meta: dict = {}
    if with_meta or not (unit and frequency):
        try:
            raw = metadata(series_id)
            meta = {"title": raw.get("title", ""),
                    "units": raw.get("units_short", ""),
                    "seasonal": raw.get("seasonal_adjustment_short", ""),
                    "updated": raw.get("last_updated", "")}
            unit = unit or meta["units"]
            frequency = frequency or _FREQ.get(raw.get("frequency", ""), "m")
        except Exception:
            pass
    return Series.from_pairs(series_id, rows, label=label or meta.get("title", series_id),
                             unit=unit, frequency=frequency or "m", source="FRED",
                             meta=meta)


def vintage_series(series_id: str, as_of: str, *, start: str = "2015-01-01") -> Series:
    """The series exactly as it was published on `as_of` — used for revisions."""
    try:
        rows = observations(series_id, start=start, realtime=(as_of, as_of))
    except Exception:
        return Series(series_id, [], [])
    return Series.from_pairs(series_id, rows, frequency="m", source="FRED")


def release_dates(release_id: int, *, limit: int = 12) -> list[str]:
    """Upcoming/recent release dates, for the 'what to watch next' panel."""
    params = {"release_id": release_id, "api_key": api_key(), "file_type": "json",
              "sort_order": "desc", "limit": limit,
              "include_release_dates_with_no_data": "true"}
    try:
        payload = get_json(build_url(f"{BASE}/release/dates", params),
                           ttl=12 * 3600, namespace="fred")
    except Exception:
        return []
    return [row["date"] for row in payload.get("release_dates", [])]
