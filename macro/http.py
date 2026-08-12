"""Polite HTTP layer: on-disk cache + per-host rate limiting + retry.

Everything the dashboard fetches goes through here. FRED bans aggressive
callers (429 escalating to 403), so requests to a given host are serialised
with a minimum spacing and every successful response is cached on disk. A
daily rebuild therefore costs one pass over the series list, and reruns
during development cost nothing.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .paths import CACHE_DIR

USER_AGENT = "macro-dashboard/1.0 (personal research; stdlib urllib)"

# Minimum seconds between requests to the same host.
HOST_SPACING = {
    "api.stlouisfed.org": 0.75,   # FRED allows ~120/min; stay well under
    "stooq.com": 0.4,
    "api.worldbank.org": 0.4,
    "data-api.ecb.europa.eu": 0.6,
    "sdmx.oecd.org": 1.0,
}
DEFAULT_SPACING = 0.5

_lock = threading.Lock()
_last_hit: dict[str, float] = {}


class FetchError(RuntimeError):
    pass


# Hosts whose TLS chain OpenSSL cannot complete on its own. Taiwan's DGBAS
# server omits the intermediate certificate; macOS fetches it via the cert's
# AIA extension, OpenSSL does not, so Python fails where curl succeeds.
# These are fetched with curl, which means verification stays fully ON and is
# performed by the system trust store — nothing is disabled.
CURL_HOSTS = {"ws.dgbas.gov.tw", "nstatdb.dgbas.gov.tw"}


def _curl(url: str, timeout: int) -> str:
    import subprocess
    result = subprocess.run(
        ["curl", "-sS", "--fail", "--location", "--max-time", str(timeout),
         "--user-agent", USER_AGENT, url],
        capture_output=True, timeout=timeout + 15)
    if result.returncode != 0:
        raise FetchError(f"curl failed ({result.returncode}): "
                         f"{result.stderr.decode('utf-8', 'replace')[:200]}")
    return result.stdout.decode("utf-8", errors="replace")


def _throttle(host: str) -> None:
    spacing = HOST_SPACING.get(host, DEFAULT_SPACING)
    with _lock:
        now = time.monotonic()
        earliest = _last_hit.get(host, 0.0) + spacing
        if earliest > now:
            time.sleep(earliest - now)
            now = earliest
        _last_hit[host] = now


def _cache_path(url: str, namespace: str) -> str:
    digest = hashlib.sha1(url.encode()).hexdigest()[:20]
    directory = os.path.join(CACHE_DIR, namespace)
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, digest + ".json.gz")


def _read_cache(path: str, ttl: float) -> str | None:
    if ttl <= 0 or not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            blob = json.load(fh)
    except Exception:
        return None
    if time.time() - blob.get("fetched_at", 0) > ttl:
        return None
    return blob.get("body")


_SECRET_PARAM = re.compile(r"((?:api_key|apikey|token|key)=)[^&]+", re.IGNORECASE)


def _redact(url: str) -> str:
    """Strip credentials before a URL is written to disk.

    The cache key is a digest of the real URL, so redacting the copy stored
    inside the blob costs nothing — and keeps the FRED key out of the
    filesystem, where a stray `git add -f` or a shared archive could leak it.
    """
    return _SECRET_PARAM.sub(r"\1REDACTED", url)


def _write_cache(path: str, url: str, body: str) -> None:
    tmp = path + ".tmp"
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump({"url": _redact(url), "fetched_at": time.time(), "body": body}, fh)
    os.replace(tmp, path)


def get(url: str, *, ttl: float = 6 * 3600, namespace: str = "http",
        retries: int = 4, timeout: int = 30, allow_stale: bool = True) -> str:
    """Fetch `url` as text, preferring a cache entry younger than `ttl` seconds.

    On repeated failure, falls back to a stale cache entry when one exists so a
    single flaky source cannot break the whole build.
    """
    path = _cache_path(url, namespace)
    cached = _read_cache(path, ttl)
    if cached is not None:
        return cached

    host = urllib.parse.urlparse(url).netloc
    last_error: Exception | None = None

    if host in CURL_HOSTS:
        for attempt in range(retries):
            _throttle(host)
            try:
                body = _curl(url, timeout)
                _write_cache(path, url, body)
                return body
            except Exception as exc:
                last_error = exc
                time.sleep(2.0 * (attempt + 1))
        if allow_stale:
            stale = _read_cache(path, ttl=float("inf"))
            if stale is not None:
                return stale
        raise FetchError(f"{url} failed: {last_error}")

    for attempt in range(retries):
        _throttle(host)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                body = raw.decode("utf-8", errors="replace")
            _write_cache(path, url, body)
            return body
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (429, 403, 503):
                # Escalating backoff: FRED keeps returning 403 for a while
                # after it decides you are hammering it.
                time.sleep(min(60.0, 4.0 * (2 ** attempt)) + random.uniform(0, 1.5))
                continue
            if exc.code == 400:
                break  # bad series id / bad params: retrying will not help
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))

    if allow_stale:
        stale = _read_cache(path, ttl=float("inf"))
        if stale is not None:
            return stale
    raise FetchError(f"{url} failed: {last_error}")


def get_json(url: str, **kwargs):
    return json.loads(get(url, **kwargs))


def build_url(base: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return base + "?" + urllib.parse.urlencode(clean)
