from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from content_clock import SHANGHAI, as_shanghai, format_shanghai
from content_contracts import ContentBlock, ContentDraft, ContentRelation
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
