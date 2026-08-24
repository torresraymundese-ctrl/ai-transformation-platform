from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from content_clock import SHANGHAI, as_shanghai, format_shanghai
from content_contracts import (
    CaseMetric,
    ContentBlock,
    ContentContractError,
    ContentDraft,
    ContentRelation,
)
from content_validation import ContentValidationError, validate_content_draft


def _draft(**changes):
    values = {
        "entry_type": "announcement",
        "slug": "platform-news",
        "title": "平台公告",
        "summary": "为中小企业提供可验证的 AI 转型信息。",
        "seo_title": "平台公告",
        "seo_description": "查看企业 AI 转型平台的最新公告。",
        "extension": {
            "valid_from": "2026-08-24 00:00:00",
            "valid_until": "2026-09-24 00:00:00",
            "cta_url": "/assessment",
        },
    }
    values.update(changes)
    return ContentDraft(**values)


def test_content_contracts_make_a_deep_immutable_copy():
    settings = {"label": "免费评估", "url": "/assessment", "style": "primary"}
    extension = {"valid_from": None, "valid_until": None, "cta_url": None}
    draft = _draft(
        blocks=(ContentBlock("cta", settings=settings),),
        extension=extension,
    )

    settings["url"] = "https://attacker.invalid"
    extension["cta_url"] = "https://attacker.invalid"

    assert draft.blocks[0].settings["url"] == "/assessment"
    assert draft.extension["cta_url"] is None
    with pytest.raises(TypeError):
        draft.extension["cta_url"] = "/changed"
    with pytest.raises(FrozenInstanceError):
        draft.title = "changed"


def test_contract_deep_freezes_nested_json_without_retaining_mutable_inputs():
    item = {"label": "第一步"}
    items = [item]
    settings = {"items": items}
    extension_nested = {"labels": ["A", {"code": "B"}]}
    block = ContentBlock("steps", settings=settings)
    draft = _draft(extension={**dict(_draft().extension), "metadata": extension_nested})

    item["label"] = "changed"
    items.append("changed")
    extension_nested["labels"][1]["code"] = "changed"

    assert block.settings["items"][0]["label"] == "第一步"
    assert len(block.settings["items"]) == 1
    assert draft.extension["metadata"]["labels"][1]["code"] == "B"


class _MutableCustom:
    def __init__(self):
        self.value = []


@pytest.mark.parametrize(
    "unsafe",
    [bytearray(b"mutable"), {"set-value"}, _MutableCustom(), float("nan"), float("inf")],
)
def test_contract_rejects_non_json_or_non_finite_nested_values(unsafe):
    with pytest.raises(ContentContractError):
        _draft(extension={**dict(_draft().extension), "unsafe": unsafe})


def test_contract_rejects_non_string_mapping_keys_without_coercion_collisions():
    with pytest.raises(ContentContractError):
        _draft(extension={1: "numeric", "1": "text"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("blocks", ({"block_type": "rich_text"},)),
        ("relations", ({"relation_type": "scenario_case"},)),
        ("metrics", ({"name": "metric"},)),
    ],
)
def test_content_draft_requires_frozen_contract_types(field, value):
    with pytest.raises(ContentContractError):
        _draft(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("slug", "a" * 81, "slug_invalid"),
        ("slug", "中文-slug", "slug_invalid"),
        ("title", "标" * 121, "title_invalid"),
        ("summary", "摘" * 301, "summary_invalid"),
        ("seo_title", "标" * 61, "seo_title_invalid"),
        ("seo_description", "摘" * 161, "seo_description_invalid"),
    ],
)
def test_content_limits_fail_with_stable_codes(field, value, code):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_draft(**{field: value}))

    assert error.value.code == code


def test_block_validation_sanitizes_html_and_enforces_exact_settings():
    draft = _draft(
        blocks=(
            ContentBlock(
                "rich_text",
                body_html='<p onclick="steal()">正文<script>alert(1)</script></p>',
                settings={},
            ),
            ContentBlock(
                "cta",
                title="下一步",
                settings={"label": "免费评估", "url": "/assessment", "style": "primary"},
                sort_order=1,
            ),
        )
    )

    validated = validate_content_draft(draft)

    assert validated.blocks[0].body_html == "<p>正文</p>"
    assert validated.blocks[1].settings == {
        "label": "免费评估",
        "url": "/assessment",
        "style": "primary",
    }

    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(
            _draft(
                blocks=(
                    ContentBlock(
                        "cta",
                        settings={
                            "label": "错误链接",
                            "url": "http://example.com",
                            "style": "primary",
                            "onclick": "steal()",
                        },
                    ),
                )
            )
        )
    assert error.value.code == "block_settings_invalid"


@pytest.mark.parametrize("settings", [None, "not-a-mapping", 7])
def test_non_mapping_block_settings_have_one_stable_validation_error(settings):
    block = ContentBlock("rich_text", body_html="<p>正文</p>", settings=settings)

    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_draft(blocks=(block,)))

    assert error.value.code == "block_settings_invalid"


def test_malformed_cta_port_fails_with_the_stable_validation_code():
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(
            _draft(
                blocks=(
                    ContentBlock(
                        "cta",
                        settings={
                            "label": "错误链接",
                            "url": "https://example.com:not-a-port/path",
                            "style": "primary",
                        },
                    ),
                )
            )
        )

    assert error.value.code == "block_settings_invalid"


def test_resource_source_url_rejects_control_characters_before_persistence():
    source_url = "https://example.com/report\r\nX-Test: injected"
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(
            ContentDraft(
                entry_type="resource",
                slug="unsafe-source",
                title="来源测试",
                summary="验证来源 URL 不能携带控制字符或注入请求头。",
                seo_title="来源测试",
                seo_description="验证安全且可审核的资源来源地址。",
                extension={
                    "resource_type": "report",
                    "is_original": 0,
                    "source_name": "Example",
                    "source_url": source_url,
                },
            )
        )

    assert error.value.code == "source_url_invalid"


@pytest.mark.parametrize(
    "url",
    [
        "/safe\\evil",
        "/safe\u202eevil",
        "/safe%ZZ",
        "https://bad_host.example/path",
        "https://example.com/%ZZ",
    ],
)
def test_cta_rejects_ambiguous_control_percent_and_host_shapes(url):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(
            _draft(
                blocks=(
                    ContentBlock(
                        "cta",
                        settings={"label": "安全链接", "url": url, "style": "primary"},
                    ),
                )
            )
        )

    assert error.value.code == "block_settings_invalid"


@pytest.mark.parametrize(
    ("draft", "code"),
    [
        (_draft(blocks=tuple(ContentBlock("heading", title=str(i)) for i in range(41))), "too_many_blocks"),
        (_draft(relations=tuple(ContentRelation("industry_case", i, i) for i in range(51))), "too_many_relations"),
        (
            _draft(
                blocks=(
                    ContentBlock(
                        "steps",
                        settings={"items": [[{"label": "too deep"}]]},
                    ),
                )
            ),
            "block_settings_too_deep",
        ),
    ],
)
def test_aggregate_limits_reject_oversized_or_deep_structures(draft, code):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(draft)
    assert error.value.code == code


def test_clock_converts_utc_to_explicit_second_precision_shanghai_time():
    instant = datetime(2026, 8, 24, 16, 0, 0, 987654, tzinfo=timezone.utc)

    converted = as_shanghai(instant)

    assert converted.tzinfo == SHANGHAI
    assert format_shanghai(instant) == "2026-08-25 00:00:00"
    with pytest.raises(ValueError, match="timezone-aware"):
        as_shanghai(datetime(2026, 8, 24, 16, 0, 0))


@pytest.mark.parametrize(
    "publish_at",
    ["2026-02-30 10:00:00", "2026-13-01 10:00:00", "2026-08-24T10:00:00"],
)
def test_publish_at_must_be_a_real_shanghai_calendar_second(publish_at):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_draft(publish_at=publish_at))

    assert error.value.code == "publish_at_invalid"


def test_extension_timestamps_must_be_real_calendar_seconds():
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(
            _draft(
                extension={
                    "valid_from": "2026-02-30 10:00:00",
                    "valid_until": "2026-09-24 00:00:00",
                    "cta_url": None,
                }
            )
        )
    assert error.value.code == "extension_invalid"


def _metric(**changes):
    values = {
        "name": "处理时间",
        "before_value": "8",
        "after_value": "2",
        "unit": "小时",
        "statistical_period": "连续 30 天",
        "evidence_explanation": "由项目交付记录中的人工与自动化时长对比得出。",
        "sort_order": 99,
    }
    values.update(changes)
    return CaseMetric(**values)


def _case_draft(*, metrics):
    return ContentDraft(
        entry_type="case",
        slug="metric-case",
        title="指标案例",
        summary="用于验证结构化指标边界和排序的案例内容。",
        seo_title="指标案例",
        seo_description="验证案例指标的类型、长度、数量和排序规则。",
        extension={
            "verification_code": "verified-internal-record",
            "is_anonymized": 1,
            "basis_type": "private_authorization",
            "private_basis_reference": "internal-delivery-record-001",
            "source_url": None,
            "source_url_sha256": None,
            "source_check_code": None,
            "source_checked_at": None,
            "source_check_expires_at": None,
            "source_check_url_sha256": None,
            "is_verified": 1,
            "review_confirmed": 1,
            "verified_at": "2026-08-24 09:00:00",
        },
        metrics=metrics,
    )


def test_case_metrics_are_bounded_and_reindexed_by_the_server():
    first = _metric(sort_order=50)
    second = _metric(name="人工步骤", sort_order=10)

    validated = validate_content_draft(_case_draft(metrics=(first, second)))

    assert tuple(metric.sort_order for metric in validated.metrics) == (0, 1)


def test_case_metric_count_is_limited_to_twenty():
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_case_draft(metrics=tuple(_metric(name=str(i)) for i in range(21))))
    assert error.value.code == "too_many_metrics"


def test_non_case_content_cannot_carry_case_metrics():
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_draft(metrics=(_metric(),)))
    assert error.value.code == "metrics_not_allowed"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"name": ""}, "metric_name_invalid"),
        ({"name": "n" * 121}, "metric_name_invalid"),
        ({"before_value": "b" * 121}, "metric_before_invalid"),
        ({"after_value": "a" * 121}, "metric_after_invalid"),
        ({"unit": "u" * 41}, "metric_unit_invalid"),
        ({"statistical_period": "p" * 121}, "metric_period_invalid"),
        ({"evidence_explanation": "e" * 1001}, "metric_evidence_invalid"),
        ({"sort_order": -1}, "metric_order_invalid"),
        ({"sort_order": True}, "metric_order_invalid"),
    ],
)
def test_case_metric_fields_have_literal_schema_limits(changes, code):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_case_draft(metrics=(_metric(**changes),)))
    assert error.value.code == code
