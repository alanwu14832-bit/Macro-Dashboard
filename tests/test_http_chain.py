"""伺服器漏送中介憑證時把憑證鏈補回來（macro/http.py）。

主計總處的 ws.dgbas.gov.tw 只送自己的憑證，Python 與 curl 都回
「unable to get local issuer certificate」——台灣 CPI 因此在雲端建置裡一直是缺口。
修法是照憑證上的 AIA 網址把中介憑證抓回來接上，跟瀏覽器做的一樣。

這是全站唯一一段碰憑證驗證的程式，寫錯不會報錯，只會悄悄把驗證放寬。所以釘死：

  1. 只在「找不到簽發者」這一個錯誤時才補。過期、主機名不符照樣失敗。
  2. 自己簽自己的憑證（根憑證）絕不收進信任庫——AIA 的網址來自還沒驗過的憑證，
     收了等於讓對方自己指定信任起點。
  3. 「部分鏈」必須關著，鏈的終點只能是系統信任庫裡的根憑證。

測試不連網：憑證是手刻的最小 DER，只有這裡會讀到的那幾欄。
"""
from __future__ import annotations

import ssl
import unittest
import urllib.error
from unittest import mock

from macro import http

CA_ISSUERS = bytes.fromhex("06082b06010505073002")
OCSP = bytes.fromhex("06082b06010505073001")


def tlv(tag: int, value: bytes) -> bytes:
    size = len(value)
    if size < 0x80:
        head = bytes([size])
    else:
        raw = size.to_bytes((size.bit_length() + 7) // 8, "big")
        head = bytes([0x80 | len(raw)]) + raw
    return bytes([tag]) + head + value


def seq(*parts: bytes) -> bytes:
    return tlv(0x30, b"".join(parts))


def name(common_name: str) -> bytes:
    return seq(tlv(0x31, seq(tlv(0x06, bytes.fromhex("550403")), tlv(0x0C, common_name.encode()))))


def cert(issuer: str, subject: str, *, aia: str | None = None, ocsp: str | None = None,
         v1: bool = False) -> bytes:
    access = b""
    if ocsp:
        access += seq(OCSP, tlv(0x86, ocsp.encode()))
    if aia:
        access += seq(CA_ISSUERS, tlv(0x86, aia.encode()))
    fields = [] if v1 else [tlv(0xA0, tlv(0x02, b"\x02"))]
    fields += [tlv(0x02, b"\x01"), seq(tlv(0x06, b"\x2a")), name(issuer), seq(), name(subject), seq()]
    if access:
        fields.append(tlv(0xA3, seq(seq(tlv(0x04, seq(access))))))
    return seq(seq(*fields), seq(), tlv(0x03, b"\x00"))


LEAF = cert("中介 CA", "ws.example.gov.tw", aia="http://ca.example/inter.crt",
            ocsp="http://ocsp.example/")
INTER = cert("根 CA", "中介 CA", aia="http://ca.example/root.crt")
ROOT = cert("根 CA", "根 CA")


def verify_error(code: int) -> ssl.SSLCertVerificationError:
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_code = code
    return error


class ReadingCertificates(unittest.TestCase):
    def test_issuer_and_subject(self):
        issuer, subject = http.cert_names(LEAF)
        self.assertEqual(issuer, name("中介 CA"))
        self.assertEqual(subject, name("ws.example.gov.tw"))

    def test_v1_certificate_has_no_version_field(self):
        issuer, subject = http.cert_names(cert("A", "B", v1=True))
        self.assertEqual((issuer, subject), (name("A"), name("B")))

    def test_only_a_root_is_self_issued(self):
        self.assertFalse(http.self_issued(LEAF))
        self.assertFalse(http.self_issued(INTER))
        self.assertTrue(http.self_issued(ROOT))

    def test_issuer_url_is_the_ca_issuers_entry_not_ocsp(self):
        self.assertEqual(http.issuer_urls(LEAF), ["http://ca.example/inter.crt"])
        self.assertEqual(http.issuer_urls(ROOT), [])

    def test_only_http_urls_are_followed(self):
        self.assertEqual(http.issuer_urls(cert("A", "B", aia="ldap://ca.example/cn=A")), [])
        self.assertEqual(http.issuer_urls(cert("A", "B", aia="file:///etc/passwd")), [])

    def test_long_url_uses_long_form_length(self):
        url = "http://ca.example/" + "x" * 200 + ".crt"
        self.assertEqual(http.issuer_urls(cert("A", "B", aia=url)), [url])


class WhenToRepair(unittest.TestCase):
    def test_only_a_missing_issuer_is_repairable(self):
        self.assertTrue(http.chain_incomplete(verify_error(20)))
        self.assertTrue(http.chain_incomplete(verify_error(21)))
        self.assertTrue(http.chain_incomplete(urllib.error.URLError(verify_error(20))))

    def test_expired_or_wrong_host_still_fails(self):
        for code in (10, 62, 18, 19):       # 過期、主機名不符、自簽、鏈裡有自簽
            self.assertFalse(http.chain_incomplete(verify_error(code)), code)
            self.assertFalse(http.chain_incomplete(urllib.error.URLError(verify_error(code))), code)

    def test_other_errors_are_not_certificate_problems(self):
        self.assertFalse(http.chain_incomplete(urllib.error.URLError("timed out")))
        self.assertFalse(http.chain_incomplete(ssl.SSLError("handshake failure")))
        self.assertFalse(http.chain_incomplete(ValueError("x")))


class StrictContext(unittest.TestCase):
    def test_verification_is_on_and_partial_chains_are_off(self):
        context = http._strict_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        partial = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
        self.assertEqual(context.verify_flags & partial, 0)

    def test_partial_chain_default_of_newer_pythons_is_cleared(self):
        """Python 3.13 起預設開著部分鏈；不清掉的話，補進來的中介憑證自己就是信任起點。"""
        partial = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0)
        if not partial:
            self.skipTest("這個 Python 沒有 VERIFY_X509_PARTIAL_CHAIN")
        loose = ssl.create_default_context()
        loose.verify_flags |= partial
        with mock.patch.object(http.ssl, "create_default_context", return_value=loose):
            self.assertEqual(http._strict_context().verify_flags & partial, 0)


class FakeContext:
    def __init__(self):
        self.loaded: list[str] = []

    def load_verify_locations(self, cadata=None):
        self.loaded.append(cadata)


class CompletingTheChain(unittest.TestCase):
    def run_chain(self, leaf, served: dict, verifies_after: int):
        context = FakeContext()
        fetched = []

        def fetch(url, _timeout):
            fetched.append(url)
            return served[url]

        with mock.patch.object(http, "_strict_context", return_value=context), \
             mock.patch.object(http, "_peer_cert", return_value=leaf), \
             mock.patch.object(http, "_fetch_cert", side_effect=fetch), \
             mock.patch.object(http, "_verifies",
                               side_effect=lambda *_a: len(context.loaded) >= verifies_after):
            try:
                result = http.complete_chain("ws.example.gov.tw", 443, 5)
            except http.FetchError as error:
                result = error
        return result, context, fetched

    def test_missing_intermediate_is_added_and_nothing_else(self):
        result, context, fetched = self.run_chain(
            LEAF, {"http://ca.example/inter.crt": INTER}, verifies_after=1)
        self.assertEqual(result[1], ["http://ca.example/inter.crt"])
        self.assertEqual(context.loaded, [ssl.DER_cert_to_PEM_cert(INTER)])
        self.assertEqual(fetched, ["http://ca.example/inter.crt"])      # 沒有去抓根憑證

    def test_a_self_issued_certificate_is_never_trusted(self):
        """憑證上的網址來自還沒驗過的憑證。它指向一張自簽憑證時，收下就等於
        讓對方自己指定信任起點——整個驗證就沒有意義了。"""
        forged = cert("攻擊者", "ws.example.gov.tw", aia="http://evil.example/root.crt")
        result, context, _ = self.run_chain(
            forged, {"http://evil.example/root.crt": cert("攻擊者", "攻擊者")}, verifies_after=1)
        self.assertIsInstance(result, http.FetchError)
        self.assertEqual(context.loaded, [])

    def test_root_reached_while_climbing_is_not_added(self):
        result, context, fetched = self.run_chain(
            LEAF, {"http://ca.example/inter.crt": INTER, "http://ca.example/root.crt": ROOT},
            verifies_after=99)                                          # 系統信任庫裡沒有這個根
        self.assertIsInstance(result, http.FetchError)
        self.assertEqual(context.loaded, [ssl.DER_cert_to_PEM_cert(INTER)])
        self.assertEqual(fetched[-1], "http://ca.example/root.crt")

    def test_two_missing_intermediates(self):
        upper = cert("根 CA", "上層中介", aia="http://ca.example/root.crt")
        lower = cert("上層中介", "中介 CA", aia="http://ca.example/upper.crt")
        result, context, _ = self.run_chain(
            LEAF, {"http://ca.example/inter.crt": lower, "http://ca.example/upper.crt": upper},
            verifies_after=2)
        self.assertEqual(result[1], ["http://ca.example/inter.crt", "http://ca.example/upper.crt"])
        self.assertEqual(len(context.loaded), 2)

    def test_no_issuer_url_means_no_repair(self):
        result, context, fetched = self.run_chain(cert("中介 CA", "ws.example.gov.tw"), {}, 1)
        self.assertIsInstance(result, http.FetchError)
        self.assertEqual((context.loaded, fetched), ([], []))

    def test_climb_is_bounded(self):
        """每一張都指向下一張、永遠到不了根：不能無限抓下去。"""
        served = {f"http://ca.example/{i}.crt": cert(f"CA{i + 1}", f"CA{i}", aia=f"http://ca.example/{i + 1}.crt")
                  for i in range(1, 20)}
        leaf = cert("CA1", "ws.example.gov.tw", aia="http://ca.example/1.crt")
        result, context, fetched = self.run_chain(leaf, served, verifies_after=99)
        self.assertIsInstance(result, http.FetchError)
        self.assertEqual(len(fetched), http.MAX_CHAIN_DEPTH)


class Opening(unittest.TestCase):
    def setUp(self):
        http._chain_contexts.clear()
        http.CHAINS_COMPLETED.clear()
        self.addCleanup(http._chain_contexts.clear)
        self.addCleanup(http.CHAINS_COMPLETED.clear)

    def open(self, url, outcomes):
        """outcomes：urlopen 每次被呼叫時要丟的例外或要回的值。回傳 (結果, 呼叫紀錄)。"""
        calls = []
        queue = list(outcomes)

        def fake_urlopen(_request, timeout=None, context=None):
            calls.append(context)
            outcome = queue.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        repaired = object()
        with mock.patch.object(http.urllib.request, "urlopen", side_effect=fake_urlopen), \
             mock.patch.object(http, "complete_chain",
                               return_value=(repaired, ["http://ca.example/inter.crt"])) as completer:
            try:
                result = http._open(http.urllib.request.Request(url), 5)
            except Exception as error:      # noqa: BLE001 — 測的就是哪一種會傳出來
                result = error
        return result, calls, completer, repaired

    def test_healthy_host_never_touches_the_repair_path(self):
        result, calls, completer, _ = self.open("https://api.example/x", ["body"])
        self.assertEqual(result, "body")
        self.assertEqual(calls, [None])
        completer.assert_not_called()
        self.assertEqual(http.CHAINS_COMPLETED, {})

    def test_missing_issuer_is_repaired_once_and_recorded(self):
        result, calls, completer, repaired = self.open(
            "https://ws.example.gov.tw/x", [urllib.error.URLError(verify_error(20)), "body"])
        self.assertEqual(result, "body")
        self.assertEqual(calls, [None, repaired])
        completer.assert_called_once_with("ws.example.gov.tw", 443, 5)
        self.assertEqual(http.CHAINS_COMPLETED,
                         {"ws.example.gov.tw": "http://ca.example/inter.crt"})
        # 同一台主機第二次：直接用補好的 context，不再補一次
        again, calls, completer, _ = self.open("https://ws.example.gov.tw/y", ["again"])
        self.assertEqual(again, "again")
        self.assertEqual(calls, [repaired])
        completer.assert_not_called()

    def test_expired_certificate_is_not_repaired(self):
        result, calls, completer, _ = self.open(
            "https://ws.example.gov.tw/x", [urllib.error.URLError(verify_error(10))])
        self.assertIsInstance(result, urllib.error.URLError)
        self.assertEqual(calls, [None])
        completer.assert_not_called()

    def test_failure_after_repair_is_not_retried_forever(self):
        result, calls, completer, repaired = self.open(
            "https://ws.example.gov.tw/x",
            [urllib.error.URLError(verify_error(20)), urllib.error.URLError(verify_error(20))])
        self.assertIsInstance(result, urllib.error.URLError)
        self.assertEqual(calls, [None, repaired])
        completer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
