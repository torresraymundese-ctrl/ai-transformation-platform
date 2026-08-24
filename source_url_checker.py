"""Pinned, bounded HTTP transport for reviewed content-source checks."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
import zlib

from content_clock import as_shanghai, format_shanghai
from content_contracts import SourceCheckResult


ONE_MIB = 1_048_576
MAX_REDIRECTS = 3
MAX_DNS_ANSWERS = 8
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    code: str
    final_url: str
    status: int | None
    content_type: str | None
    body: bytes


def _normalized_host(host):
    try:
        return host.encode("idna").decode("ascii").lower().rstrip(".")
    except (AttributeError, UnicodeError):
        return ""


def _normalize_url(url):
    if not isinstance(url, str) or not url.strip():
        return None, "invalid_url"
    if "\\" in url or any(ord(character) < 32 or ord(character) == 127 for character in url):
        return None, "invalid_url"
    try:
        parsed = urlsplit(url.strip())
        host = _normalized_host(parsed.hostname)
        port = parsed.port
    except ValueError:
        return None, "invalid_url"
    if parsed.username is not None or parsed.password is not None:
        return None, "userinfo_not_allowed"
    if not parsed.scheme or not host:
        return None, "invalid_url"
    scheme = parsed.scheme.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    if port is not None and port != default_port:
        return None, "port_not_allowed"
    path = quote(parsed.path or "/", safe="/%:@-._~!$&'()*+,;=")
    query = quote(parsed.query, safe="=&/%:@-._~!$'()*+,;?")
    netloc = f"[{host}]" if ":" in host else host
    return urlunsplit((scheme, netloc, path, query, "")), None


def normalize_source_url(url):
    """Return the transport's canonical URL and a generic validation code."""
    return _normalize_url(url)


class _PinnedConnection:
    def __init__(self, scheme, host, ip, port, connect_timeout, read_timeout):
        self.scheme = scheme
        self.host = host
        self.ip = ip
        self.port = port
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self._connection = self._build()

    def _build(self):
        wrapper = self

        if self.scheme == "https":
            class PinnedHTTPSConnection(http.client.HTTPSConnection):
                def connect(self):
                    raw = socket.create_connection(
                        (wrapper.ip, wrapper.port), wrapper.connect_timeout
                    )
                    raw.settimeout(wrapper.read_timeout)
                    self.sock = self._context.wrap_socket(
                        raw, server_hostname=wrapper.host
                    )

            return PinnedHTTPSConnection(
                self.host,
                self.port,
                timeout=self.read_timeout,
                context=ssl.create_default_context(),
            )

        class PinnedHTTPConnection(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.create_connection(
                    (wrapper.ip, wrapper.port), wrapper.connect_timeout
                )
                self.sock.settimeout(wrapper.read_timeout)

        return PinnedHTTPConnection(self.host, self.port, timeout=self.read_timeout)

    def request(self, method, target, *, headers):
        self._connection.request(method, target, headers=headers)

    def getresponse(self):
        return self._connection.getresponse()

    @property
    def peer_ip(self):
        return self._connection.sock.getpeername()[0]

    def close(self):
        self._connection.close()


class PinnedHttpTransport:
    def __init__(
        self,
        *,
        resolver=None,
        connection_factory=None,
        connect_timeout=3.0,
        read_timeout=5.0,
        max_dns_answers=MAX_DNS_ANSWERS,
    ):
        self._resolver = resolver
        self._connection_factory = connection_factory or _PinnedConnection
        self.connect_timeout = float(connect_timeout)
        self.read_timeout = float(read_timeout)
        self.max_dns_answers = int(max_dns_answers)

    def _resolve(self, host, port):
        if self._resolver is not None:
            return tuple(dict.fromkeys(self._resolver(host, port)))
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return tuple(dict.fromkeys(answer[4][0] for answer in answers))

    def fetch(
        self,
        url,
        *,
        allowed_hosts,
        allowed_schemes,
        max_compressed_bytes,
        max_decompressed_bytes,
        allowed_content_types,
    ):
        normalized_hosts = frozenset(_normalized_host(host) for host in allowed_hosts)
        normalized_schemes = frozenset(str(scheme).lower() for scheme in allowed_schemes)
        if "" in normalized_hosts or any("*" in host for host in normalized_hosts):
            return FetchResult(False, "host_not_allowed", "", None, None, b"")
        current = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            normalized, error = _normalize_url(current)
            if error:
                return FetchResult(False, error, "", None, None, b"")
            parsed = urlsplit(normalized)
            if parsed.scheme not in normalized_schemes:
                return FetchResult(False, "scheme_not_allowed", normalized, None, None, b"")
            if parsed.hostname not in normalized_hosts:
                return FetchResult(False, "host_not_allowed", normalized, None, None, b"")
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            try:
                answers = self._resolve(parsed.hostname, port)
            except (OSError, socket.gaierror):
                return FetchResult(False, "dns_failed", normalized, None, None, b"")
            if not answers:
                return FetchResult(False, "dns_failed", normalized, None, None, b"")
            if len(answers) > self.max_dns_answers:
                return FetchResult(False, "dns_answer_limit", normalized, None, None, b"")
            try:
                parsed_answers = tuple(ipaddress.ip_address(answer) for answer in answers)
            except ValueError:
                return FetchResult(False, "dns_failed", normalized, None, None, b"")
            if any(not address.is_global for address in parsed_answers):
                return FetchResult(False, "unsafe_address", normalized, None, None, b"")
            pinned_ip = str(parsed_answers[0])
            connection = None
            try:
                connection = self._connection_factory(
                    parsed.scheme,
                    parsed.hostname,
                    pinned_ip,
                    port,
                    self.connect_timeout,
                    self.read_timeout,
                )
                target = parsed.path or "/"
                if parsed.query:
                    target += f"?{parsed.query}"
                host_header = (
                    f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
                )
                if parsed.port is not None:
                    host_header = f"{host_header}:{parsed.port}"
                connection.request(
                    "GET",
                    target,
                    headers={
                        "Host": host_header,
                        "Accept-Encoding": "gzip, deflate",
                        "Connection": "close",
                        "User-Agent": "AIPlatformSourceCheck/1.0",
                    },
                )
                response = connection.getresponse()
                try:
                    peer = ipaddress.ip_address(connection.peer_ip)
                except (ValueError, OSError):
                    return FetchResult(False, "peer_mismatch", normalized, None, None, b"")
                if peer != parsed_answers[0] or not peer.is_global:
                    return FetchResult(False, "peer_mismatch", normalized, None, None, b"")
                if response.status in REDIRECT_STATUSES:
                    location = response.getheader("Location")
                    if not location:
                        return FetchResult(False, "redirect_invalid", normalized, response.status, None, b"")
                    if redirect_count == MAX_REDIRECTS:
                        return FetchResult(False, "too_many_redirects", normalized, response.status, None, b"")
                    current = urljoin(normalized, location)
                    continue
                content_type = (response.getheader("Content-Type", "").split(";", 1)[0].strip().lower())
                if response.status < 200 or response.status >= 300:
                    return FetchResult(False, "http_status", normalized, response.status, content_type or None, b"")
                if content_type not in allowed_content_types:
                    return FetchResult(False, "content_type_not_allowed", normalized, response.status, content_type or None, b"")
                body, size_error = _read_bounded_body(
                    response,
                    response.getheader("Content-Encoding", "").strip().lower(),
                    int(max_compressed_bytes),
                    int(max_decompressed_bytes),
                )
                if size_error:
                    return FetchResult(False, size_error, normalized, response.status, content_type, b"")
                return FetchResult(True, "https_ok", normalized, response.status, content_type, body)
            except (OSError, ssl.SSLError, http.client.HTTPException):
                return FetchResult(False, "network_error", normalized, None, None, b"")
            finally:
                if connection is not None:
                    connection.close()
        return FetchResult(False, "too_many_redirects", "", None, None, b"")


def _read_bounded_body(response, content_encoding, compressed_limit, decompressed_limit):
    if content_encoding not in {"", "identity", "gzip", "deflate"}:
        return b"", "content_encoding_not_allowed"
    decompressor = None
    if content_encoding == "gzip":
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif content_encoding == "deflate":
        decompressor = zlib.decompressobj()
    compressed_count = 0
    output = bytearray()
    try:
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            compressed_count += len(chunk)
            if compressed_count > compressed_limit:
                return b"", "response_too_large"
            if decompressor is None:
                decoded = chunk
            else:
                remaining = decompressed_limit - len(output)
                decoded = decompressor.decompress(chunk, remaining + 1)
                if decompressor.unconsumed_tail:
                    return b"", "response_too_large"
            output.extend(decoded)
            if len(output) > decompressed_limit:
                return b"", "response_too_large"
        if decompressor is not None:
            output.extend(decompressor.flush(decompressed_limit - len(output) + 1))
            if not decompressor.eof:
                return b"", "content_encoding_invalid"
        if len(output) > decompressed_limit:
            return b"", "response_too_large"
    except zlib.error:
        return b"", "content_encoding_invalid"
    return bytes(output), None


def check_source_url(url, transport: PinnedHttpTransport, now: datetime):
    checked = as_shanghai(now)
    normalized, error = _normalize_url(url)
    if normalized is None:
        normalized = ""
        digest = hashlib.sha256(str(url).encode("utf-8")).hexdigest()
        return SourceCheckResult(
            False,
            error or "invalid_url",
            normalized,
            digest,
            digest,
            format_shanghai(checked),
            format_shanghai(checked + timedelta(days=7)),
        )
    host = urlsplit(normalized).hostname
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    try:
        fetched = transport.fetch(
            normalized,
            allowed_hosts=frozenset({host}),
            allowed_schemes=frozenset({"https"}),
            max_compressed_bytes=ONE_MIB,
            max_decompressed_bytes=ONE_MIB,
            allowed_content_types=frozenset({"text/html", "text/plain", "application/pdf"}),
        )
    except Exception:
        fetched = FetchResult(False, "network_error", normalized, None, None, b"")
    final_url = fetched.final_url or normalized
    final_digest = hashlib.sha256(final_url.encode("utf-8")).hexdigest()
    return SourceCheckResult(
        fetched.ok,
        fetched.code,
        final_url,
        digest,
        final_digest,
        format_shanghai(checked),
        format_shanghai(checked + timedelta(days=7)),
    )
