from dataclasses import dataclass, field, FrozenInstanceError, replace
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
from content_validation import (
    ContentValidationError,
    is_valid_public_budget_range,
    is_valid_public_week_range,
    validate_content_draft,
)


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


class _UnhashableString(str):
    __hash__ = None


def test_contract_rejects_non_exact_maturity_code_strings_before_validation():
    with pytest.raises(ContentContractError):
        _draft(maturity_codes=(_UnhashableString("explore"),))


@dataclass(frozen=True)
class _MutableBlockSubclass(ContentBlock):
    mutable_extra: list = field(default_factory=list)


@dataclass(frozen=True)
class _MutableRelationSubclass(ContentRelation):
    mutable_extra: list = field(default_factory=list)


@dataclass(frozen=True)
class _MutableMetricSubclass(CaseMetric):
    mutable_extra: list = field(default_factory=list)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("blocks", (_MutableBlockSubclass("rich_text"),)),
        ("relations", (_MutableRelationSubclass("industry_case", 1),)),
        (
            "metrics",
            (
                _MutableMetricSubclass(
                    "处理时间",
                    "8",
                    "2",
                    "小时",
                    "连续 30 天",
                    "由项目记录验证。",
                ),
            ),
        ),
    ],
)
def test_contract_rejects_dataclass_subclasses_with_mutable_extra_state(
    field_name, value
):
    with pytest.raises(ContentContractError):
        _draft(**{field_name: value})


def test_contract_rejects_cyclic_json_with_a_stable_contract_error():
    cyclic = {}
    cyclic["self"] = cyclic

    with pytest.raises(ContentContractError):
        _draft(extension={**dict(_draft().extension), "cyclic": cyclic})


def test_contract_rejects_json_beyond_the_finite_depth_budget():
    nested = "leaf"
    for _ in range(70):
        nested = {"child": nested}

    with pytest.raises(ContentContractError):
        _draft(extension={**dict(_draft().extension), "nested": nested})


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


def test_service_maturity_is_explicit_nonempty_and_owner_scoped():
    service = _draft(
        entry_type="service",
        extension={"service_id": 1},
        maturity_codes=("explore", "pilot", "scale"),
    )

    assert validate_content_draft(service).maturity_codes == (
        "explore",
        "pilot",
        "scale",
    )
    with pytest.raises(ContentValidationError, match="maturity_invalid"):
        validate_content_draft(replace(service, maturity_codes=()))
    with pytest.raises(ContentValidationError, match="maturity_invalid"):
        validate_content_draft(
            _draft(entry_type="industry", extension={"industry_id": 1}, maturity_codes=("explore",))
        )


def _external_resource(**extension_changes):
    extension = {
        "resource_type": "report",
        "is_original": 0,
        "source_name": "Example",
        "source_url": "https://example.com/report",
        "source_url_sha256": None,
        "source_check_code": None,
        "source_checked_at": None,
        "source_check_expires_at": None,
        "source_check_url_sha256": None,
        "original_published_at": "2026-08-20 09:00:00",
        "copyright_notice": "转载请注明来源",
        "attachment_media_id": None,
    }
    extension.update(extension_changes)
    return ContentDraft(
        entry_type="resource",
        slug="schema-resource",
        title="资源架构验证",
        summary="验证资源扩展字段在持久化前具有精确类型与长度约束。",
        seo_title="资源架构验证",
        seo_description="验证资源发布输入不会将类型错误泄漏到 SQLite。",
        extension=extension,
    )


def _industry_draft(*, relations):
    return ContentDraft(
        entry_type="industry",
        slug="schema-industry",
        title="行业关系验证",
        summary="验证内容关系目标和排序字段的精确整数类型。",
        seo_title="行业关系验证",
        seo_description="验证布尔值不能伪装成内容关系外键或排序值。",
        extension={"industry_id": 1},
        relations=relations,
    )


@pytest.mark.parametrize(
    ("draft", "code"),
    [
        (_draft(content_group_id=True), "content_group_id_invalid"),
        (_draft(share_image_media_id=True), "share_image_media_invalid"),
        (
            _draft(
                blocks=(
                    ContentBlock(
                        "image_text",
                        settings={"alignment": "left", "alt_text": "图片"},
                        media_asset_id=True,
                    ),
                )
            ),
            "block_media_invalid",
        ),
        (
            _draft(blocks=(ContentBlock("rich_text", sort_order=True),)),
            "block_order_invalid",
        ),
        (
            _draft(blocks=(ContentBlock("heading", settings={"level": 2.0}),)),
            "block_settings_invalid",
        ),
        (
            ContentDraft(
                entry_type="scenario",
                slug="bool-scenario-id",
                title="场景类型验证",
                summary="验证布尔值不能被静默当作整数场景 ID。",
                seo_title="场景类型验证",
                seo_description="验证核心场景外键必须是真实正整数。",
                extension={"scenario_id": True},
                maturity_codes=("explore",),
            ),
            "extension_invalid",
        ),
        (
            _industry_draft(relations=(ContentRelation("industry_case", True),)),
            "relation_target_invalid",
        ),
        (
            _industry_draft(relations=(ContentRelation("industry_case", 1, True),)),
            "relation_order_invalid",
        ),
        (_external_resource(is_original=True), "extension_invalid"),
        (_external_resource(attachment_media_id=True), "extension_invalid"),
    ],
)
def test_ids_flags_orders_and_heading_level_require_exact_integers(draft, code):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(draft)

    assert error.value.code == code


@pytest.mark.parametrize(
    ("draft", "code"),
    [
        (_draft(entry_type=[]), "entry_type_invalid"),
        (_draft(blocks=(ContentBlock([], settings={}),)), "block_type_invalid"),
        (
            _draft(blocks=(ContentBlock("rich_text", body_html=[]),)),
            "block_body_invalid",
        ),
        (
            _draft(
                blocks=(
                    ContentBlock(
                        "cta",
                        settings={
                            "label": "继续",
                            "url": "/assessment",
                            "style": [],
                        },
                    ),
                )
            ),
            "block_settings_invalid",
        ),
        (
            _industry_draft(relations=(ContentRelation([], 1),)),
            "relation_type_invalid",
        ),
        (_external_resource(source_name=[]), "extension_invalid"),
        (_external_resource(source_name="s" * 201), "extension_invalid"),
        (_external_resource(copyright_notice=[]), "extension_invalid"),
        (_external_resource(copyright_notice="c" * 501), "extension_invalid"),
    ],
)
def test_unhashable_and_oversized_schema_values_have_stable_validation_errors(
    draft, code
):
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(draft)

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


@pytest.mark.parametrize(
    "extension_change",
    [
        {"verification_code": []},
        {"is_anonymized": True},
        {"is_verified": True},
        {"review_confirmed": True},
        {"source_check_code": [], "source_checked_at": "2026-08-24 09:00:00", "source_check_expires_at": "2026-08-31 09:00:00", "source_check_url_sha256": "a" * 64},
    ],
)
def test_case_extension_scalars_and_flags_require_exact_schema_types(
    extension_change
):
    draft = _case_draft(metrics=())
    invalid = replace(
        draft,
        extension={**dict(draft.extension), **extension_change},
    )

    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(invalid)

    assert error.value.code == "extension_invalid"


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


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("title", "title_invalid"),
        ("summary", "summary_invalid"),
        ("seo_title", "seo_title_invalid"),
        ("seo_description", "seo_description_invalid"),
    ),
)
def test_top_level_public_text_rejects_nul_with_its_stable_code(field, code):
    """Catch a persisted NUL that strip-only top-level validation used to accept."""
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_draft(**{field: f"有效\x00{field}"}))

    assert error.value.code == code


class _FloatSubclass(float):
    pass


class _IntSubclass(int):
    pass


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    (
        (True, 2),
        (_IntSubclass(1), 2),
        (_FloatSubclass(1.0), 2.0),
        (float("nan"), 2.0),
        (float("inf"), float("inf")),
    ),
)
def test_public_budget_range_requires_finite_exact_int_or_float_endpoints(minimum, maximum):
    assert not is_valid_public_budget_range(minimum, maximum)


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    (
        (True, 2),
        (_IntSubclass(1), 2),
        (1.5, 2.5),
        (1, 2.0),
    ),
)
def test_public_week_range_requires_exact_positive_integer_endpoints(minimum, maximum):
    assert not is_valid_public_week_range(minimum, maximum)


def test_whitespace_only_optional_block_title_normalizes_to_none():
    """Keep optional title blanks out of persistence without rejecting a valid body."""
    validated = validate_content_draft(
        _draft(
            blocks=(
                ContentBlock(
                    "heading", title=" \t ", body_html="<p>可见正文</p>",
                    settings={"level": 2},
                ),
            ),
        )
    )

    assert validated.blocks[0].title is None


def test_optional_block_title_rejects_nul_with_stable_title_error():
    """Reject a control character rather than normalizing it into an optional title."""
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(
            _draft(blocks=(ContentBlock("heading", title="标题\x00", settings={"level": 2}),))
        )

    assert error.value.code == "block_title_invalid"


@pytest.mark.parametrize(
    "block",
    (
        ContentBlock("image_text", settings={"alignment": "left", "alt_text": "图\x00示"}),
        ContentBlock("metric", settings={"value": "10\x00", "unit": "项"}),
        ContentBlock("metric", settings={"value": "10", "unit": "项\x00"}),
        ContentBlock("steps", settings={"items": ("步骤\x00一",)}),
        ContentBlock("download", settings={"label": "下载\x00"}),
        ContentBlock("cta", settings={"label": "开始\x00", "url": "/assessment", "style": "primary"}),
    ),
    ids=("image-alt", "metric-value", "metric-unit", "step-item", "download-label", "cta-label"),
)
def test_block_plain_text_settings_reject_nul_with_stable_settings_error(block):
    """Prevent a control character in a renderer-consumed setting from persisting."""
    with pytest.raises(ContentValidationError) as error:
        validate_content_draft(_draft(blocks=(block,)))

    assert error.value.code == "block_settings_invalid"
