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
import socket
import ssl
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
    # 台灣各部會統計資料庫：密集連打時會直接丟連線（不是 4xx），
    # 回來的是空值而且不會報錯。
    "nstatdb.dgbas.gov.tw": 1.5,
    "statdb.mol.gov.tw": 1.2,
    "web02.mof.gov.tw": 1.2,
    "statis.moi.gov.tw": 1.2,
    "service.moea.gov.tw": 0.8,
    "www.stat.gov.tw": 1.0,
    "www.cbc.gov.tw": 0.8,
    "data.gov.tw": 0.6,
}
DEFAULT_SPACING = 0.5

# build.py --offline 時設成 True：一律只讀快取（不論新舊），沒有快取就直接失敗、
# 不連網。原本靠各來源自己把 ttl 設成無限，新加的來源各有自己的短 TTL，
# 結果「離線」建置照樣連網。
OFFLINE = False

_lock = threading.Lock()
_last_hit: dict[str, float] = {}


class FetchError(RuntimeError):
    pass


# 主計總處總體統計資料庫照舊走 curl（它現在送得出完整的憑證鏈，curl 與 Python 都驗得過；
# 這條路跑了很久沒出事，不動它）。驗證是開著的，由系統信任庫執行。
#
# ws.dgbas.gov.tw 原本也在這裡，理由是「macOS 的 curl 會自己補中介憑證」——那只對
# 用 SecureTransport 驗證的 curl 成立。GitHub Actions 的 curl 是 OpenSSL，本機新版的
# curl 是 LibreSSL，兩邊都補不了，所以台灣 CPI 在雲端建置裡從來沒有抓到過。
# 現在改由下面的 _open() 照憑證上寫的網址把中介憑證補回來。
CURL_HOSTS = {"nstatdb.dgbas.gov.tw"}


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


# ---------------------------------------------------------------- 憑證鏈 ----
#
# 有些伺服器只送自己的憑證、不送簽發它的中介憑證（主計總處的 ws.dgbas.gov.tw）。
# 瀏覽器會照憑證上的 AIA（Authority Information Access）網址把中介憑證抓回來接上，
# OpenSSL 不會，於是 Python 與 curl 都回「unable to get local issuer certificate」。
# 這裡做的是瀏覽器做的那件事，而且只在遇到那一個錯誤時才做。
#
# 驗證沒有關，也沒有放寬——這一點要靠三件事守住，少一件就等於信任了一張
# 從明文 HTTP 抓來的憑證：
#   1. 補進來的只准是中介憑證。自己簽自己的（根憑證）一律不收；根憑證只認
#      系統信任庫裡的。
#   2. 關掉「部分鏈」。Python 3.13 起 create_default_context() 預設開著它，
#      開著的話信任庫裡任何一張憑證都能當鏈的終點——包括剛補進來的那張。
#   3. 補完之後照常做完整驗證（簽章、效期、主機名），鏈的終點必須是系統的根憑證。

MAX_CERT_BYTES = 64 * 1024
MAX_CHAIN_DEPTH = 3
# X509_V_ERR_UNABLE_TO_GET_ISSUER_CERT_LOCALLY、X509_V_ERR_UNABLE_TO_VERIFY_LEAF_SIGNATURE：
# 兩個都是「找不到簽發者」。過期（10）、主機名不符（62）不在這裡——那些補不了，也不該補。
_MISSING_ISSUER = {20, 21}
# AIA 裡「CA Issuers」這個存取方式的 OID（1.3.6.1.5.5.7.48.2）
_CA_ISSUERS_OID = bytes.fromhex("06082b06010505073002")

_chain_contexts: dict[str, ssl.SSLContext] = {}
# 這一輪替哪些主機補過憑證鏈：{主機: 中介憑證的來源網址}。build.py 會印出來。
CHAINS_COMPLETED: dict[str, str] = {}


def _tlv(data: bytes, at: int) -> tuple[int, int, int]:
    """DER 的一個元素：回傳 (標籤, 內容起點, 內容終點)。"""
    tag, first = data[at], data[at + 1]
    if first < 0x80:
        start = at + 2
        return tag, start, start + first
    size = first & 0x7F
    start = at + 2 + size
    return tag, start, start + int.from_bytes(data[at + 2:at + 2 + size], "big")


def cert_names(der: bytes) -> tuple[bytes, bytes]:
    """憑證的 (簽發者, 主體)，各是一段原始的 DER。只走到 tbsCertificate 的前幾欄。"""
    _tag, at, _end = _tlv(der, 0)               # Certificate
    _tag, at, end = _tlv(der, at)               # tbsCertificate
    fields = []
    while at < end and len(fields) < 6:
        tag, _start, stop = _tlv(der, at)
        fields.append((tag, der[at:stop]))
        at = stop
    if fields and fields[0][0] == 0xA0:         # [0] version，v1 憑證沒有這一欄
        fields = fields[1:]
    # serialNumber, signature, issuer, validity, subject
    return fields[2][1], fields[4][1]


def self_issued(der: bytes) -> bool:
    issuer, subject = cert_names(der)
    return issuer == subject


def issuer_urls(der: bytes) -> list[str]:
    """憑證上寫的「簽發者憑證在哪裡」。只收 http(s)；OCSP 的網址不算。"""
    urls, at = [], 0
    while True:
        at = der.find(_CA_ISSUERS_OID, at)
        if at < 0:
            return urls
        at += len(_CA_ISSUERS_OID)
        try:
            tag, start, stop = _tlv(der, at)
        except IndexError:
            return urls
        if tag == 0x86:                         # GeneralName: uniformResourceIdentifier
            url = der[start:stop].decode("ascii", "replace")
            if url.lower().startswith(("http://", "https://")):
                urls.append(url)


def _strict_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.verify_flags &= ~getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
    return context


def _peer_cert(host: str, port: int, timeout: int) -> bytes:
    """伺服器送來的那一張憑證。這條連線不驗證、也不傳任何資料，只為了讀憑證上的網址；
    讀到的東西不被信任——信不信要等補完鏈之後的完整驗證決定。"""
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    probe.check_hostname = False
    probe.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as raw:
        with probe.wrap_socket(raw, server_hostname=host) as tls:
            return tls.getpeercert(binary_form=True)


def _fetch_cert(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        blob = response.read(MAX_CERT_BYTES + 1)
    if len(blob) > MAX_CERT_BYTES:
        raise FetchError(f"{url} 不像一張憑證（超過 {MAX_CERT_BYTES} bytes）")
    if b"-----BEGIN CERTIFICATE-----" in blob:
        return ssl.PEM_cert_to_DER_cert(blob.decode("ascii", "replace"))
    return blob


def _verifies(host: str, port: int, context: ssl.SSLContext, timeout: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host):
                return True
    except ssl.SSLError:
        return False


def complete_chain(host: str, port: int, timeout: int) -> tuple[ssl.SSLContext, list[str]]:
    """系統信任庫＋這台主機漏送的中介憑證。回傳 (驗證用的 context, 補了哪些網址)。

    一層一層往上補，補到驗得過為止；遇到自己簽自己的就停——那是根憑證，
    根憑證不是抓來的東西可以決定的。
    """
    context = _strict_context()
    der = _peer_cert(host, port, timeout)
    added: list[str] = []
    for _ in range(MAX_CHAIN_DEPTH):
        urls = issuer_urls(der)
        if not urls:
            break
        der = _fetch_cert(urls[0], timeout)
        if self_issued(der):
            break
        context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
        added.append(urls[0])
        if _verifies(host, port, context, timeout):
            return context, added
    raise FetchError(f"{host} 的憑證鏈補不起來（補了 {len(added)} 張中介憑證仍驗不過）")


def chain_incomplete(exc: BaseException) -> bool:
    """這個錯誤是不是「伺服器漏送中介憑證」。其他的憑證錯誤一律照原樣失敗。"""
    reason = getattr(exc, "reason", exc)
    return (isinstance(reason, ssl.SSLCertVerificationError)
            and getattr(reason, "verify_code", None) in _MISSING_ISSUER)


def _open(request: urllib.request.Request, timeout: int):
    """urlopen；伺服器漏送中介憑證時補上再試一次。同一台主機一輪只補一次。"""
    parsed = urllib.parse.urlparse(request.full_url)
    context = _chain_contexts.get(parsed.netloc)
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=context)
    except urllib.error.URLError as exc:
        if context is not None or parsed.scheme != "https" or not chain_incomplete(exc):
            raise
    context, added = complete_chain(parsed.hostname, parsed.port or 443, timeout)
    _chain_contexts[parsed.netloc] = context
    CHAINS_COMPLETED[parsed.netloc] = added[0]
    return urllib.request.urlopen(request, timeout=timeout, context=context)


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
        retries: int = 4, timeout: int = 30, allow_stale: bool = True,
        headers: dict | None = None, validate=None) -> str:
    """Fetch `url` as text, preferring a cache entry younger than `ttl` seconds.

    On repeated failure, falls back to a stale cache entry when one exists so a
    single flaky source cannot break the whole build.

    `validate(body) -> bool`：內容不合格的回應不寫入快取，快取裡不合格的也當作沒有。
    央行的新聞稿頁還沒上線時會 302 轉到首頁、最後回 200——沒有這道檢查，
    首頁會以那篇新聞稿的網址被快取一週，整週都讀不到決議。
    """
    ok = validate or (lambda _body: True)
    path = _cache_path(url, namespace)
    cached = _read_cache(path, float("inf") if OFFLINE else ttl)
    if cached is not None and ok(cached):
        return cached
    if OFFLINE:
        raise FetchError(f"--offline：{_redact(url)} 沒有可用的快取")

    host = urllib.parse.urlparse(url).netloc
    last_error: Exception | None = None

    if host in CURL_HOSTS:
        for attempt in range(retries):
            _throttle(host)
            try:
                body = _curl(url, timeout)
            except Exception as exc:
                last_error = exc
                time.sleep(2.0 * (attempt + 1))
                continue
            if not ok(body):
                last_error = FetchError("回應內容沒有通過檢查，不寫入快取")
                break
            _write_cache(path, url, body)
            return body
        if allow_stale:
            stale = _read_cache(path, ttl=float("inf"))
            if stale is not None and ok(stale):
                return stale
        raise FetchError(f"{url} failed: {last_error}")

    for attempt in range(retries):
        _throttle(host)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
                          **(headers or {})})
        try:
            with _open(request, timeout) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                body = raw.decode("utf-8", errors="replace")
            if not ok(body):
                last_error = FetchError("回應內容沒有通過檢查，不寫入快取")
                break
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
        if stale is not None and ok(stale):
            return stale
    raise FetchError(f"{url} failed: {last_error}")


def get_json(url: str, **kwargs):
    return json.loads(get(url, **kwargs))


def get_bytes(url: str, *, ttl: float = 6 * 3600, namespace: str = "http",
              retries: int = 3, timeout: int = 90,
              allow_stale: bool = True) -> bytes:
    """Fetch `url` as raw bytes, with the same on-disk cache policy as `get`.

    `get` decodes to text, which corrupts anything that is not UTF-8 — the
    國發會 landing zone ships its 景氣指標 as a ZIP. Kept separate rather than
    adding a mode flag to `get` so the text path stays the common one.
    """
    path = _cache_path(url, namespace)[:-len(".json.gz")] + ".bin.gz"
    if OFFLINE:
        ttl = float("inf")
    if ttl > 0 and os.path.exists(path):
        if time.time() - os.path.getmtime(path) <= ttl:
            try:
                with gzip.open(path, "rb") as fh:
                    return fh.read()
            except Exception:
                pass
    if OFFLINE:
        raise FetchError(f"--offline：{_redact(url)} 沒有可用的快取")

    host = urllib.parse.urlparse(url).netloc
    last_error: Exception | None = None
    for attempt in range(retries):
        _throttle(host)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with _open(request, timeout) as response:
                raw = response.read()
            tmp = path + ".tmp"
            with gzip.open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, path)
            return raw
        except Exception as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))

    if allow_stale and os.path.exists(path):
        try:
            with gzip.open(path, "rb") as fh:
                return fh.read()
        except Exception:
            pass
    raise FetchError(f"{url} failed: {last_error}")


def build_url(base: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    return base + "?" + urllib.parse.urlencode(clean)
