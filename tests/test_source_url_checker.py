from datetime import datetime
import gzip
import hashlib
import socket
import zlib

import pytest

from content_clock import SHANGHAI
from source_url_checker import PinnedHttpTransport, _PinnedConnection, check_source_url


NOW = datetime(2026, 8, 24, 10, 0, 0, tzinfo=SHANGHAI)


class FakeResponse:
    def __init__(self, *, status=200, body=b"ok", headers=None, peer_ip="93.184.216.34"):
        self.status = status
        self._body = body
        self._offset = 0
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.peer_ip = peer_ip

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size=-1):
        if self._offset >= len(self._body):
            return b""
        if size < 0:
            size = len(self._body) - self._offset
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class FakeConnection:
    def __init__(self, response):
        self.response = response
        self.request_args = None
        self.closed = False

    @property
    def peer_ip(self):
        return self.response.peer_ip

    def request(self, method, target, *, headers):
        self.request_args = (method, target, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def _transport(responses, *, answers=("93.184.216.34",)):
    resolver_calls = []
    connection_calls = []

    def resolver(host, port):
        resolver_calls.append((host, port))
        return tuple(answers)

    queue = list(responses)

    def connection_factory(scheme, host, ip, port, connect_timeout, read_timeout):
        connection_calls.append((scheme, host, ip, port, connect_timeout, read_timeout))
        return FakeConnection(queue.pop(0))

    return (
        PinnedHttpTransport(resolver=resolver, connection_factory=connection_factory),
        resolver_calls,
        connection_calls,
    )


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://user@example.com/path", "userinfo_not_allowed"),
        ("https://example.com:444/path", "port_not_allowed"),
        ("http://example.com/path", "scheme_not_allowed"),
        ("https://sub.example.com/path", "host_not_allowed"),
        ("https://example.com/\r\nX-Test: injected", "invalid_url"),
        ("https://example.com/\\evil", "invalid_url"),
    ],
)
def test_transport_rejects_disallowed_url_parts_before_dns_or_socket(url, code):
    transport, resolver_calls, connection_calls = _transport([])

    result = transport.fetch(
        url,
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is False
    assert result.code == code
    assert resolver_calls == []
    assert connection_calls == []


@pytest.mark.parametrize(
    "answers",
    [
        ("127.0.0.1",),
        ("::1",),
        ("93.184.216.34", "10.0.0.1"),
        tuple(f"93.184.216.{index}" for index in range(1, 10)),
    ],
)
def test_transport_rejects_unsafe_mixed_or_excessive_dns_answers(answers):
    transport, _, connection_calls = _transport([], answers=answers)

    result = transport.fetch(
        "https://example.com/resource",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is False
    assert result.code in {"unsafe_address", "dns_answer_limit"}
    assert connection_calls == []


def test_redirect_to_unlisted_host_is_rejected_before_second_dns_or_socket():
    transport, resolver_calls, connection_calls = _transport(
        [FakeResponse(status=302, headers={"Location": "https://evil.invalid/next"})]
    )

    result = transport.fetch(
        "https://example.com/start",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.code == "host_not_allowed"
    assert resolver_calls == [("example.com", 443)]
    assert len(connection_calls) == 1


@pytest.mark.parametrize(
    ("size", "ok"),
    [(1_048_576, True), (1_048_577, False)],
)
def test_transport_enforces_exact_uncompressed_one_mib_boundary(size, ok):
    transport, _, _ = _transport([FakeResponse(body=b"a" * size)])

    result = transport.fetch(
        "https://example.com/resource",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1_048_576,
        max_decompressed_bytes=1_048_576,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is ok
    assert result.code == ("https_ok" if ok else "response_too_large")


@pytest.mark.parametrize(
    ("size", "ok"),
    [(1_048_576, True), (1_048_577, False)],
)
def test_transport_enforces_exact_gzip_decompressed_boundary(size, ok):
    compressed = gzip.compress(b"a" * size)
    transport, _, _ = _transport(
        [
            FakeResponse(
                body=compressed,
                headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
            )
        ]
    )

    result = transport.fetch(
        "https://example.com/resource",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1_048_576,
        max_decompressed_bytes=1_048_576,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is ok
    assert result.code == ("https_ok" if ok else "response_too_large")


@pytest.mark.parametrize(
    ("encoding", "payload"),
    [
        ("gzip", gzip.compress(b"a" * 700_000) + gzip.compress(b"b" * 700_000)),
        ("gzip", gzip.compress(b"first") + gzip.compress(b"second")),
        ("gzip", gzip.compress(b"valid") + b"trailing-garbage"),
        ("deflate", zlib.compress(b"valid") + b"trailing-garbage"),
    ],
)
def test_transport_rejects_concatenated_or_trailing_compressed_data(encoding, payload):
    transport, _, _ = _transport(
        [
            FakeResponse(
                body=payload,
                headers={"Content-Type": "text/html", "Content-Encoding": encoding},
            )
        ]
    )

    result = transport.fetch(
        "https://example.com/resource",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1_048_576,
        max_decompressed_bytes=1_048_576,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is False
    assert result.code == "content_encoding_invalid"


def test_transport_verifies_the_actual_peer_matches_the_pinned_public_ip():
    transport, _, _ = _transport(
        [FakeResponse(peer_ip="93.184.216.35")], answers=("93.184.216.34",)
    )

    result = transport.fetch(
        "https://example.com/resource",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.code == "peer_mismatch"


def test_transport_rejects_a_different_resolved_peer_than_the_chosen_pin():
    transport, _, _ = _transport(
        [FakeResponse(peer_ip="93.184.216.35")],
        answers=("93.184.216.34", "93.184.216.35"),
    )

    result = transport.fetch(
        "https://example.com/resource",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.code == "peer_mismatch"


def test_source_check_wrapper_uses_exact_submitted_idna_host_and_seven_day_expiry():
    transport, resolver_calls, connection_calls = _transport([FakeResponse(body=b"valid")])

    result = check_source_url("https://EXAMPLE.com/report#section", transport, NOW)

    assert result.ok is True
    assert result.normalized_url == "https://example.com/report"
    assert result.source_url_sha256 == hashlib.sha256(
        b"https://example.com/report"
    ).hexdigest()
    assert result.source_check_url_sha256 == result.source_url_sha256
    assert result.checked_at == "2026-08-24 10:00:00"
    assert result.expires_at == "2026-08-31 10:00:00"
    assert resolver_calls == [("example.com", 443)]
    assert connection_calls[0][1:4] == ("example.com", "93.184.216.34", 443)


def test_same_host_redirect_requires_operator_to_save_and_recheck_final_url():
    redirected_transport, resolver_calls, _ = _transport(
        [
            FakeResponse(status=302, headers={"Location": "/canonical-report"}),
            FakeResponse(body=b"canonical"),
        ]
    )

    redirected = check_source_url(
        "https://example.com/old-report", redirected_transport, NOW
    )

    assert redirected.ok is False
    assert redirected.code == "redirect_requires_update"
    assert redirected.normalized_url == "https://example.com/canonical-report"
    assert redirected.source_check_url_sha256 != redirected.source_url_sha256
    assert resolver_calls == [("example.com", 443), ("example.com", 443)]

    final_transport, _, _ = _transport([FakeResponse(body=b"canonical")])
    final = check_source_url(redirected.normalized_url, final_transport, NOW)
    assert final.ok is True
    assert final.code == "https_ok"
    assert final.source_check_url_sha256 == final.source_url_sha256


def test_transport_preserves_brackets_while_pinning_a_public_ipv6_literal():
    address = "2606:4700:4700::1111"
    transport, resolver_calls, connection_calls = _transport(
        [FakeResponse(peer_ip=address)], answers=(address,)
    )

    result = transport.fetch(
        f"https://[{address}]/resource",
        allowed_hosts=frozenset({address}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is True
    assert result.final_url == f"https://[{address}]/resource"
    assert resolver_calls == [(address, 443)]
    assert connection_calls[0][2] == address


def test_bottom_tls_socket_uses_pinned_ip_sni_and_separate_timeouts(monkeypatch):
    calls = {"read_timeouts": []}

    class RawSocket:
        def settimeout(self, timeout):
            calls["read_timeouts"].append(timeout)

    raw = RawSocket()

    def create_connection(address, timeout):
        calls["socket"] = (address, timeout)
        return raw

    class Context:
        def wrap_socket(self, value, *, server_hostname):
            calls["tls"] = (value, server_hostname)
            return value

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr("ssl.create_default_context", lambda: Context())
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    connection = _PinnedConnection(
        "https", "example.com", "93.184.216.34", 443, 2.5, 7.5
    )

    connection._connection.connect()

    assert calls["socket"] == (("93.184.216.34", 443), 2.5)
    assert calls["read_timeouts"] == [7.5]
    assert calls["tls"] == (raw, "example.com")


def test_transport_passes_original_host_and_both_timeouts_to_direct_connection():
    response = FakeResponse(body=b"ok")
    connection = FakeConnection(response)
    factory_calls = []

    def factory(scheme, host, ip, port, connect_timeout, read_timeout):
        factory_calls.append(
            (scheme, host, ip, port, connect_timeout, read_timeout)
        )
        return connection

    transport = PinnedHttpTransport(
        resolver=lambda host, port: ("93.184.216.34",),
        connection_factory=factory,
        connect_timeout=2.5,
        read_timeout=7.5,
    )

    result = transport.fetch(
        "https://example.com/report?version=1",
        allowed_hosts=frozenset({"example.com"}),
        allowed_schemes=frozenset({"https"}),
        max_compressed_bytes=1024,
        max_decompressed_bytes=1024,
        allowed_content_types=frozenset({"text/html"}),
    )

    assert result.ok is True
    assert factory_calls == [
        ("https", "example.com", "93.184.216.34", 443, 2.5, 7.5)
    ]
    assert connection.request_args == (
        "GET",
        "/report?version=1",
        {
            "Host": "example.com",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
            "User-Agent": "AIPlatformSourceCheck/1.0",
        },
    )
