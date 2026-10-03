"""SSRF-safe outbound HTTP for MCP servers that fetch user-supplied URLs.

Guarantees, per request *and per redirect hop*:
  * only http/https, no URL credentials, only allow-listed ports
  * the hostname is resolved exactly once; every returned address must be public
  * the connection is made to that validated IP (Host header and TLS SNI/cert
    verification keep the original hostname), so a DNS answer that changes
    between "check" and "connect" (DNS rebinding) cannot redirect the request
  * redirects are followed manually and re-validated (max `max_redirects`)
  * response bodies are capped on *decoded* bytes (decompression bombs)

`SSRF_ALLOW_CIDRS` (comma-separated) exists for local test fixtures only and
is empty by default; never set it in production.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from urllib.parse import urljoin, urlsplit

import httpx

DEFAULT_PORTS = frozenset({80, 443, 8080, 8443})

# Address ranges that embed or tunnel IPv4 and so can smuggle a private target.
_EXTRA_BLOCKED = [
    ipaddress.ip_network(n)
    for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32", "100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15")
]

Resolver = Callable[[str, int], list[str]]


class SSRFError(Exception):
    """Request refused by the SSRF policy. Messages are safe to show to clients."""


def _allow_cidrs() -> list[ipaddress._BaseNetwork]:
    raw = os.getenv("SSRF_ALLOW_CIDRS", "")
    return [ipaddress.ip_network(c.strip()) for c in raw.split(",") if c.strip()]


def is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(ip in net for net in _allow_cidrs()):
        return True
    if any(ip in net for net in _EXTRA_BLOCKED if net.version == ip.version):
        return False
    return ip.is_global and not ip.is_multicast


def _system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError(f"Cannot resolve host {host!r}") from e
    return list(dict.fromkeys(i[4][0] for i in infos))


def resolve_public(host: str, port: int, resolver: Resolver | None = None) -> str:
    """Resolve once; return one validated IP. Every answer must be public."""
    addrs = (resolver or _system_resolver)(host, port)
    if not addrs:
        raise SSRFError(f"Cannot resolve host {host!r}")
    parsed = []
    for a in addrs:
        try:
            parsed.append(ipaddress.ip_address(a.split("%")[0]))
        except ValueError as e:
            raise SSRFError("Resolver returned an invalid address") from e
    if not all(is_public_ip(ip) for ip in parsed):
        raise SSRFError("Refusing to connect to a non-public address")
    return str(parsed[0])


def _check_url(url: str, ports: Iterable[int]) -> tuple[httpx.URL, int]:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as e:
        raise SSRFError("Invalid URL") from e
    if parts.scheme not in ("http", "https"):
        raise SSRFError("Only http(s) URLs are supported")
    if not parts.hostname:
        raise SSRFError("URL has no host")
    if parts.username or parts.password:
        raise SSRFError("URLs with embedded credentials are not allowed")
    port = port or (443 if parts.scheme == "https" else 80)
    if port not in set(ports):
        raise SSRFError(f"Port {port} is not allowed")
    return httpx.URL(url), port


@asynccontextmanager
async def safe_stream(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    max_redirects: int = 5,
    allowed_ports: Iterable[int] = DEFAULT_PORTS,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[httpx.Response]:
    """GET `url` with SSRF protection; yields the final (non-redirect) streaming response."""
    hdrs = {"User-Agent": "mcp-hub/1.0 (+fetch)", "Accept-Encoding": "gzip, deflate"}
    hdrs.update(headers or {})
    # trust_env=False: never inherit proxy/cert/netrc settings from the environment.
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=transport) as client:
        current = url
        for _ in range(max_redirects + 1):
            target, port = _check_url(current, allowed_ports)
            host = target.host
            ip = await asyncio.to_thread(resolve_public, host, port, resolver)

            pinned = target.copy_with(host=ip)  # connect to the validated IP
            req_headers = dict(hdrs)
            req_headers["Host"] = target.netloc.decode().split("@")[-1]
            req = client.build_request("GET", pinned, headers=req_headers, extensions={"sni_hostname": host})
            resp = await client.send(req, stream=True)
            if resp.is_redirect:
                location = resp.headers.get("location")
                await resp.aclose()
                if not location:
                    raise SSRFError("Redirect without Location")
                current = urljoin(current, location)
                continue
            try:
                yield resp
            finally:
                await resp.aclose()
            return
        raise SSRFError("Too many redirects")


async def read_capped(resp: httpx.Response, max_bytes: int) -> bytes:
    """Read the decoded body, aborting once it exceeds `max_bytes` (bomb-safe)."""
    declared = resp.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes and "content-encoding" not in resp.headers:
        raise SSRFError(f"Response exceeds {max_bytes // 1024} KiB limit")
    buf = bytearray()
    async for chunk in resp.aiter_bytes():
        buf.extend(chunk)
        if len(buf) > max_bytes:
            raise SSRFError(f"Response exceeds {max_bytes // 1024} KiB limit")
    return bytes(buf)


async def safe_get(url: str, *, max_bytes: int = 5 * 1024 * 1024, **kw) -> tuple[httpx.Response, bytes]:
    async with safe_stream(url, **kw) as resp:
        body = await read_capped(resp, max_bytes)
        return resp, body
