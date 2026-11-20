"""SSRF-safe HTTP for Atlas tools.

Every outbound request used by a tool goes through here. The rules are strict
on purpose:

  * http(s) only, no credentials in the URL, ports 80/443 only
  * hostname resolves only to public unicast IPs — loopback, RFC1918,
    link-local (including 169.254.169.254), reserved and IPv6 local are denied
  * DNS is resolved once and the connection is pinned to that IP, so a
    rebinding answer cannot redirect us to an internal host
  * redirects are capped and every hop is re-vetted
  * response size is capped, content type is checked, control characters are
    stripped before the text reaches a model

No cloud service, API key or third-party package is required.
"""

from __future__ import annotations

import http.client
import ipaddress
import re
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

MAX_BYTES = 256_000
MAX_REDIRECTS = 3
TIMEOUT = 8.0
USER_AGENT = "AtlasLocalTool/1.0 (+local-first; no telemetry)"

_ALLOWED_TYPES = (
    "text/html", "text/plain", "text/markdown", "text/xml", "text/css",
    "application/json", "application/xml", "application/rss+xml",
)


class NetError(Exception):
    pass


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    text: str
    truncated: bool = False


def _bad_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_loopback or ip.is_private or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def vetted_target(url: str) -> tuple[str, str, int, str, list[str]]:
    """Return (scheme, host, port, path, public IPs) or raise NetError."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise NetError("only http and https URLs are allowed")
    if parsed.username or parsed.password:
        raise NetError("URLs with credentials are not allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise NetError("URL has no host")
    port = parsed.port or (443 if scheme == "https" else 80)
    if port not in (80, 443):
        raise NetError("only ports 80 and 443 are allowed")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal:
        if _bad_ip(literal):
            raise NetError("private or special IP addresses are blocked")
        addresses = [str(literal)]
    else:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise NetError(f"could not resolve {host}") from exc
        addresses = sorted({info[4][0] for info in infos})
        if not addresses:
            raise NetError(f"could not resolve {host}")
        for raw in addresses:
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise NetError("invalid DNS answer") from exc
            if _bad_ip(ip):
                raise NetError("host resolves to a private or special IP")

    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return scheme, host, port, path, addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a vetted IP while presenting the real host for TLS SNI."""

    def __init__(self, ip: str, host: str, port: int, context: ssl.SSLContext):
        super().__init__(ip, port, timeout=TIMEOUT, context=context)
        self._pinned_ip = ip
        self._sni_host = host

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self._sni_host)


def _tls_context() -> ssl.SSLContext:
    # python.org macOS builds do not load the system keychain by default.
    system_ca = Path("/etc/ssl/cert.pem")
    if system_ca.exists():
        return ssl.create_default_context(cafile=str(system_ca))
    return ssl.create_default_context()


def _connection(scheme: str, ip: str, port: int, host: str):
    if scheme == "https":
        return _PinnedHTTPSConnection(ip, host, port, _tls_context())
    return http.client.HTTPConnection(ip, port, timeout=TIMEOUT)


def _clean(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)


def fetch(
    url: str,
    *,
    max_bytes: int = MAX_BYTES,
    headers: dict[str, str] | None = None,
    require_text: bool = True,
) -> Response:
    """Fetch a public URL safely. Raises NetError on any policy violation."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, path, addresses = vetted_target(current)
        conn = _connection(scheme, addresses[0], port, host)
        request_headers = {
            "Host": host if port in (80, 443) else f"{host}:{port}",
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.5",
            "Connection": "close",
        }
        request_headers.update(headers or {})
        try:
            conn.request("GET", path, headers=request_headers)
            response = conn.getresponse()
            location = response.getheader("Location")
            if response.status in (301, 302, 303, 307, 308) and location:
                response.read()
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise NetError(f"HTTP {response.status} from {host}")
            content_type = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
            if require_text and content_type and not any(
                content_type.startswith(allowed) for allowed in _ALLOWED_TYPES
            ):
                raise NetError(f"unsupported content type: {content_type}")

            chunks, total = [], 0
            truncated = False
            while True:
                chunk = response.read(min(8192, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    truncated = True
                    chunks.append(chunk[: max(0, max_bytes - (total - len(chunk)))])
                    break
                chunks.append(chunk)
            body = b"".join(chunks).decode("utf-8", errors="replace")
            return Response(
                url=current,
                status=response.status,
                content_type=content_type or "text/plain",
                text=_clean(body) + ("\n[truncated]" if truncated else ""),
                truncated=truncated,
            )
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise NetError(f"request failed: {type(exc).__name__}") from exc
        finally:
            conn.close()
    raise NetError("too many redirects")
