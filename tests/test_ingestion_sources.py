import json
from datetime import datetime
import inspect
from pathlib import Path

import pytest

from ingestion_contracts import FetchedItem
from ingestion_service import run_enabled_sources
from ingestion_sources import (
    SourceRegistryError,
    fetch_reviewed_source,
    load_source_registry,
    source_policy,
)
import scraper
from source_url_checker import FetchResult


NOW = datetime.fromisoformat("2026-08-31T10:00:00+08:00")
ROOT = Path(__file__).resolve().parents[1]


def _registry_file(tmp_path, source, *, extras=None):
    payload = {"version": 1, "sources": [source]}
    if extras:
        payload.update(extras)
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _source(**overrides):
    source = {
        "code": "reviewed_news",
        "name": "经审核来源",
        "url": "https://例子.测试/feed",
        "hosts": ["例子.测试", "cdn.例子.测试"],
        "adapter": "plain_text",
        "scheme": "https",
        "license_basis_reference": "terms_2026_08",
        "robots_policy": "allow",
        "retain_body": False,
        "enabled": False,
    }
    source.update(overrides)
    return source


def test_checked_in_production_registry_is_empty_until_sources_are_real_reviewed(
    monkeypatch,
):
    monkeypatch.delenv("AI_PLATFORM_INGESTION_SOURCE_CODES", raising=False)
    registry = load_source_registry(
        ROOT / "seed_data" / "ingestion_sources_v1.json"
    )

    assert registry == ()


def test_only_reviewed_exact_codes_can_be_enabled_from_environment(tmp_path, monkeypatch):
    path = _registry_file(tmp_path, _source())
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")

    policy = load_source_registry(path)[0]

    assert policy.enabled is True
    assert policy.hosts == frozenset({"xn--fsqu00a.xn--0zwm56d", "cdn.xn--fsqu00a.xn--0zwm56d"})
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news,unknown")
    with pytest.raises(SourceRegistryError, match="source_enablement_invalid"):
        load_source_registry(path)


def test_runtime_apis_accept_registry_paths_but_not_raw_policy_collections():
    assert "enabled_codes" not in inspect.signature(load_source_registry).parameters
    assert "registry_path" in inspect.signature(source_policy).parameters
    assert "registry" not in inspect.signature(source_policy).parameters
    assert "registry_path" in inspect.signature(run_enabled_sources).parameters
    assert "registry" not in inspect.signature(run_enabled_sources).parameters
    assert "registry_path" in inspect.signature(scraper.run_scraper).parameters
    assert "registry" not in inspect.signature(scraper.run_scraper).parameters


def test_runtime_registry_path_still_runs_the_complete_schema_loader(
    tmp_path, monkeypatch
):
    path = _registry_file(tmp_path, _source(enabled=True))
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")

    with pytest.raises(SourceRegistryError, match="source_policy_invalid"):
        run_enabled_sources(registry_path=path, now=NOW)


@pytest.mark.parametrize(
    "mutation",
    [
        {"code": "Reviewed"},
        {"hosts": ["*.example.com"]},
        {"scheme": "ftp"},
        {"robots_policy": "unknown"},
        {"retain_body": 1},
        {"enabled": True},
        {"unexpected": "field"},
    ],
)
def test_registry_rejects_unreviewed_or_malformed_policy(tmp_path, monkeypatch, mutation):
    monkeypatch.delenv("AI_PLATFORM_INGESTION_SOURCE_CODES", raising=False)
    path = _registry_file(tmp_path, _source(**mutation))

    with pytest.raises(SourceRegistryError):
        load_source_registry(path)


def test_http_requires_explicit_reviewed_scheme(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_PLATFORM_INGESTION_SOURCE_CODES", raising=False)
    rejected = _registry_file(
        tmp_path,
        _source(url="http://example.com/feed", hosts=["example.com"]),
    )
    with pytest.raises(SourceRegistryError, match="source_url_invalid"):
        load_source_registry(rejected)

    allowed = _registry_file(
        tmp_path,
        _source(
            url="http://example.com/feed",
            hosts=["example.com"],
            scheme="http",
        ),
    )
    assert load_source_registry(allowed)[0].scheme == "http"


class RecordingTransport:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def fetch(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.result


def _plain_adapter(policy, result, now):
    assert policy.code == "reviewed_news"
    assert now == NOW
    text = result.body.decode("utf-8")
    return (
        FetchedItem(
            source_code=policy.code,
            source_name=policy.name,
            url=result.final_url,
            title="固定标题",
            summary=text,
            body_html=f"<p>{text}</p>",
            original_published_at=now,
        ),
    )


def test_fetch_uses_pinned_transport_policy_once_and_discards_unlicensed_body(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    policy = load_source_registry(_registry_file(tmp_path, _source()))[0]
    transport = RecordingTransport(
        FetchResult(
            True,
            "https_ok",
            "https://xn--fsqu00a.xn--0zwm56d/feed",
            200,
            "text/plain",
            b"licensed summary",
        )
    )

    items = fetch_reviewed_source(
        policy,
        transport=transport,
        adapters={"plain_text": _plain_adapter},
        now=NOW,
    )

    assert len(transport.calls) == 1
    url, options = transport.calls[0]
    assert url == policy.url
    assert options == {
        "allowed_hosts": policy.hosts,
        "allowed_schemes": frozenset({"https"}),
        "max_compressed_bytes": 2_097_152,
        "max_decompressed_bytes": 2_097_152,
        "allowed_content_types": frozenset(
            {"text/html", "text/plain", "application/json", "application/xml"}
        ),
    }
    assert items[0].summary == "licensed summary"
    assert items[0].body_html == ""


def test_fetch_retains_body_only_when_policy_explicitly_allows_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    policy = load_source_registry(
        _registry_file(tmp_path, _source(retain_body=True))
    )[0]
    transport = RecordingTransport(
        FetchResult(True, "https_ok", policy.url, 200, "text/plain", b"body")
    )

    items = fetch_reviewed_source(
        policy, transport=transport, adapters={"plain_text": _plain_adapter}, now=NOW
    )

    assert items[0].body_html == "<p>body</p>"


def test_adapter_cannot_replace_fixed_source_identity_or_url(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    policy = load_source_registry(_registry_file(tmp_path, _source()))[0]
    transport = RecordingTransport(
        FetchResult(True, "https_ok", policy.url, 200, "text/plain", b"body")
    )

    def hostile_adapter(_policy, _result, now):
        return (
            FetchedItem(
                "unreviewed",
                "伪造来源",
                "https://attacker.invalid/discovery?secret=1",
                "标题",
                "摘要",
                "",
                now,
            ),
        )

    with pytest.raises(SourceRegistryError, match="source_adapter_failed"):
        fetch_reviewed_source(
            policy,
            transport=transport,
            adapters={"plain_text": hostile_adapter},
            now=NOW,
        )


@pytest.mark.parametrize("code", ["network_error", "http_status", "response_too_large"])
def test_fetch_failure_is_generic_and_adapter_is_not_called(tmp_path, monkeypatch, code):
    monkeypatch.setenv("AI_PLATFORM_INGESTION_SOURCE_CODES", "reviewed_news")
    policy = load_source_registry(_registry_file(tmp_path, _source()))[0]
    transport = RecordingTransport(
        FetchResult(False, code, policy.url + "?secret=1", 502, "text/html", b"remote")
    )

    with pytest.raises(SourceRegistryError, match="source_fetch_failed") as error:
        fetch_reviewed_source(
            policy,
            transport=transport,
            adapters={"plain_text": lambda *_: pytest.fail("adapter called")},
            now=NOW,
        )

    assert code not in str(error.value)
    assert "secret" not in str(error.value)
    assert "remote" not in str(error.value)
