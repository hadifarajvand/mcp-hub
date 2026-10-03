"""Unit tests for servers/common/ssrf.py (run: pytest tests/test_ssrf.py)."""
import asyncio
import gzip
import ipaddress
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "servers", "common"))
import ssrf  # noqa: E402
from ssrf import SSRFError  # noqa: E402

PUBLIC = "93.184.216.34"


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.0.1",
    "224.0.0.1", "::1", "fe80::1", "fd00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254",
    "64:ff9b::7f00:1", "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "198.18.0.1",
])
def test_non_public_ips_blocked(ip):
    assert not ssrf.is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("ip", ["8.8.8.8", PUBLIC, "2606:4700:4700::1111"])
def test_public_ips_allowed(ip):
    assert ssrf.is_public_ip(ipaddress.ip_address(ip))


@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "017700000001", "127.1", "0", "localhost", "127.0.0.1.nip.io"])
def test_obfuscated_loopback_hosts_never_resolve_public(host):
    # System resolver: obfuscated forms resolve to loopback (or fail); both must end in SSRFError.
    with pytest.raises(SSRFError):
        ssrf.resolve_public(host, 80)


def test_mixed_answers_rejected():
    with pytest.raises(SSRFError):
        ssrf.resolve_public("x.test", 80, lambda h, p: [PUBLIC, "10.0.0.5"])


class Recorder:
    def __init__(self, handler):
        self.requests = []
        self.transport = httpx.MockTransport(lambda r: (self.requests.append(r), handler(r))[1])


def run(coro):
    return asyncio.run(coro)


def test_connects_to_pinned_ip_keeps_host_and_sni_resolves_once():
    calls = []

    def resolver(host, port):
        calls.append(host)
        return [PUBLIC]

    rec = Recorder(lambda r: httpx.Response(200, text="ok"))
    resp, body = run(ssrf.safe_get("https://example.test/path?q=1", resolver=resolver, transport=rec.transport))
    req = rec.requests[0]
    assert body == b"ok" and calls == ["example.test"]
    assert req.url.host == PUBLIC and req.url.path == "/path" and req.url.query == b"q=1"
    assert req.headers["host"] == "example.test"
    assert req.extensions["sni_hostname"] == "example.test"


def test_dns_rebinding_second_answer_is_never_used():
    answers = iter([[PUBLIC], ["127.0.0.1"], ["127.0.0.1"]])
    rec = Recorder(lambda r: httpx.Response(200, text="ok"))
    run(ssrf.safe_get("http://rebind.test/", resolver=lambda h, p: next(answers), transport=rec.transport))
    assert [r.url.host for r in rec.requests] == [PUBLIC]


def test_redirect_to_private_is_blocked_and_never_requested():
    table = {"public.test": [PUBLIC], "internal.test": ["10.0.0.5"]}
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "http://internal.test/admin"}))
    with pytest.raises(SSRFError):
        run(ssrf.safe_get("http://public.test/", resolver=lambda h, p: table[h], transport=rec.transport))
    assert len(rec.requests) == 1


def test_redirect_to_metadata_ip_literal_blocked():
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"}))
    with pytest.raises(SSRFError):
        run(ssrf.safe_get("http://public.test/", resolver=lambda h, p: [PUBLIC] if h == "public.test" else ssrf._system_resolver(h, p),
                          transport=rec.transport))
    assert len(rec.requests) == 1


def test_redirect_loop_limited():
    rec = Recorder(lambda r: httpx.Response(302, headers={"location": "/again"}))
    with pytest.raises(SSRFError, match="Too many redirects"):
        run(ssrf.safe_get("http://loop.test/", resolver=lambda h, p: [PUBLIC], transport=rec.transport))
    assert len(rec.requests) == 6


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "gopher://x.test/", "ftp://x.test/", "http://user:pw@x.test/", "http://x.test:22/",
    "http://x.test:6379/", "http:///nohost", "javascript:alert(1)", "http://[::1]/", "http://[::ffff:7f00:1]/",
])
def test_bad_urls_rejected(url):
    rec = Recorder(lambda r: httpx.Response(200))
    with pytest.raises(SSRFError):
        run(ssrf.safe_get(url, resolver=lambda h, p: [PUBLIC], transport=rec.transport) if "[" not in url
            else ssrf.safe_get(url, transport=rec.transport))
    assert rec.requests == []


def test_declared_oversize_rejected():
    rec = Recorder(lambda r: httpx.Response(200, headers={"content-length": "999999999"}, content=b"x"))
    with pytest.raises(SSRFError, match="exceeds"):
        run(ssrf.safe_get("http://big.test/", max_bytes=1000, resolver=lambda h, p: [PUBLIC], transport=rec.transport))


def test_streamed_oversize_rejected():
    rec = Recorder(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(SSRFError, match="exceeds"):
        run(ssrf.safe_get("http://big.test/", max_bytes=1000, resolver=lambda h, p: [PUBLIC], transport=rec.transport))


def test_gzip_bomb_capped_on_decoded_bytes():
    bomb = gzip.compress(b"\0" * (50 * 1024 * 1024))  # ~50 KB on the wire, 50 MiB decoded
    assert len(bomb) < 100_000
    rec = Recorder(lambda r: httpx.Response(200, headers={"content-encoding": "gzip"}, content=bomb))
    with pytest.raises(SSRFError, match="exceeds"):
        run(ssrf.safe_get("http://bomb.test/", max_bytes=1024 * 1024, resolver=lambda h, p: [PUBLIC], transport=rec.transport))


def test_allow_cidrs_only_when_explicitly_set(monkeypatch):
    assert not ssrf.is_public_ip(ipaddress.ip_address("10.9.9.9"))
    monkeypatch.setenv("SSRF_ALLOW_CIDRS", "10.9.9.0/24")
    assert ssrf.is_public_ip(ipaddress.ip_address("10.9.9.9"))
    assert not ssrf.is_public_ip(ipaddress.ip_address("10.9.8.9"))
