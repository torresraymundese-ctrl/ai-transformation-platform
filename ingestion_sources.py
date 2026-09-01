"""Reviewed, fixed content-source policies and bounded adapter execution."""

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import json
import os
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ingestion_contracts import FetchedItem, require_source_code
from source_url_checker import FetchResult, normalize_source_url


REGISTRY_PATH = Path(__file__).resolve().parent / "seed_data" / "ingestion_sources_v1.json"
MAX_BODY_BYTES = 2_097_152
ALLOWED_CONTENT_TYPES = frozenset(
    {"text/html", "text/plain", "application/json", "application/xml"}
)
_CODE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_POLICY_KEYS = frozenset(
    {
        "code",
        "name",
        "url",
        "hosts",
        "adapter",
        "scheme",
        "license_basis_reference",
        "robots_policy",
        "retain_body",
        "enabled",
    }
)


class SourceRegistryError(ValueError):
    """A reviewed source cannot be enabled or fetched safely."""


@dataclass(frozen=True)
class SourcePolicy:
    code: str
    name: str
    url: str
    hosts: frozenset[str]
    adapter: str
    scheme: str
    license_basis_reference: str
    robots_policy: str
    retain_body: bool
    enabled: bool


def _host(value):
    if type(value) is not str or not value or "*" in value:
        raise SourceRegistryError("source_host_invalid")
    try:
        normalized = value.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise SourceRegistryError("source_host_invalid") from error
    if (
        not normalized
        or len(normalized) > 253
        or any(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) is None
            for label in normalized.split(".")
        )
    ):
        raise SourceRegistryError("source_host_invalid")
    return normalized


def _policy(raw):
    if type(raw) is not dict or frozenset(raw) != _POLICY_KEYS:
        raise SourceRegistryError("source_policy_invalid")
    try:
        code = require_source_code(raw["code"])
    except ValueError as error:
        raise SourceRegistryError("source_code_invalid") from error
    if (
        type(raw["name"]) is not str
        or not raw["name"].strip()
        or raw["name"] != raw["name"].strip()
        or len(raw["name"]) > 200
        or type(raw["adapter"]) is not str
        or _CODE.fullmatch(raw["adapter"]) is None
        or type(raw["license_basis_reference"]) is not str
        or _CODE.fullmatch(raw["license_basis_reference"]) is None
        or raw["robots_policy"] not in {"allow", "disallow"}
        or type(raw["retain_body"]) is not bool
        or raw["enabled"] is not False
        or raw["scheme"] not in {"https", "http"}
        or type(raw["hosts"]) is not list
        or not raw["hosts"]
    ):
        raise SourceRegistryError("source_policy_invalid")
    hosts = frozenset(_host(host) for host in raw["hosts"])
    normalized_url, error = normalize_source_url(raw["url"])
    if error or not normalized_url:
        raise SourceRegistryError("source_url_invalid")
    parsed = urlsplit(normalized_url)
    if parsed.scheme != raw["scheme"] or parsed.hostname not in hosts:
        raise SourceRegistryError("source_url_invalid")
    return SourcePolicy(
        code=code,
        name=raw["name"],
        url=normalized_url,
        hosts=hosts,
        adapter=raw["adapter"],
        scheme=raw["scheme"],
        license_basis_reference=raw["license_basis_reference"],
        robots_policy=raw["robots_policy"],
        retain_body=raw["retain_body"],
        enabled=False,
    )


def _enabled_codes(value):
    if value in (None, ""):
        return frozenset()
    if type(value) is not str:
        raise SourceRegistryError("source_enablement_invalid")
    parts = value.split(",")
    if any(_CODE.fullmatch(part) is None for part in parts) or len(parts) != len(set(parts)):
        raise SourceRegistryError("source_enablement_invalid")
    return frozenset(parts)


def load_source_registry(path=None):
    """Load the exact reviewed registry; enable only environment-listed codes."""
    registry_path = REGISTRY_PATH if path is None else path
    try:
        payload = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SourceRegistryError("source_registry_invalid") from error
    if (
        type(payload) is not dict
        or frozenset(payload) != {"version", "sources"}
        or payload["version"] != 1
        or type(payload["sources"]) is not list
    ):
        raise SourceRegistryError("source_registry_invalid")
    policies = tuple(_policy(raw) for raw in payload["sources"])
    codes = tuple(policy.code for policy in policies)
    if len(codes) != len(set(codes)):
        raise SourceRegistryError("source_registry_invalid")
    requested = _enabled_codes(os.environ.get("AI_PLATFORM_INGESTION_SOURCE_CODES"))
    if not requested.issubset(codes):
        raise SourceRegistryError("source_enablement_invalid")
    return tuple(replace(policy, enabled=policy.code in requested) for policy in policies)


def source_policy(source_code, *, registry_path=None):
    policies = load_source_registry(registry_path)
    for policy in policies:
        if policy.code == source_code:
            return policy
    raise SourceRegistryError("source_not_reviewed")


def _plain_text_adapter(policy, result, now):
    text = result.body.decode("utf-8", errors="strict").strip()
    if not text:
        return ()
    title = text.splitlines()[0].strip()[:300]
    summary = " ".join(text.split())[:2000]
    return (
        FetchedItem(
            policy.code,
            policy.name,
            result.final_url,
            title,
            summary,
            f"<p>{summary}</p>",
            now,
        ),
    )


def _html_summary_adapter(policy, result, now):
    soup = BeautifulSoup(result.body, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else policy.name
    summary = " ".join(soup.get_text(" ", strip=True).split())[:2000]
    if not summary:
        return ()
    return (
        FetchedItem(
            policy.code,
            policy.name,
            result.final_url,
            title[:300],
            summary,
            str(soup.body or ""),
            now,
        ),
    )


SOURCE_ADAPTERS = {
    "plain_text": _plain_text_adapter,
    "html_summary": _html_summary_adapter,
}


def fetch_reviewed_source(policy, *, transport, adapters=None, now: datetime):
    """Fetch one fixed reviewed URL exactly once through the pinned transport."""
    if type(policy) is not SourcePolicy or not policy.enabled or policy.robots_policy != "allow":
        raise SourceRegistryError("source_fetch_not_allowed")
    adapter_map = SOURCE_ADAPTERS if adapters is None else adapters
    adapter = adapter_map.get(policy.adapter)
    if not callable(adapter):
        raise SourceRegistryError("source_adapter_invalid")
    try:
        result = transport.fetch(
            policy.url,
            allowed_hosts=policy.hosts,
            allowed_schemes=frozenset({policy.scheme}),
            max_compressed_bytes=MAX_BODY_BYTES,
            max_decompressed_bytes=MAX_BODY_BYTES,
            allowed_content_types=ALLOWED_CONTENT_TYPES,
        )
    except Exception as error:
        raise SourceRegistryError("source_fetch_failed") from error
    if type(result) is not FetchResult or result.ok is not True:
        raise SourceRegistryError("source_fetch_failed")
    try:
        final_host = _host(urlsplit(result.final_url).hostname)
        items = adapter(policy, result, now)
    except Exception as error:
        raise SourceRegistryError("source_adapter_failed") from error
    if final_host not in policy.hosts or type(items) is not tuple or any(
        type(item) is not FetchedItem for item in items
    ):
        raise SourceRegistryError("source_adapter_failed")
    for item in items:
        item_url, item_error = normalize_source_url(item.url)
        parsed_item = urlsplit(item_url or "")
        if (
            item.source_code != policy.code
            or item.source_name != policy.name
            or item_error
            or parsed_item.scheme != policy.scheme
            or parsed_item.hostname not in policy.hosts
        ):
            raise SourceRegistryError("source_adapter_failed")
    return tuple(replace(item, body_html=item.body_html if policy.retain_body else "") for item in items)
