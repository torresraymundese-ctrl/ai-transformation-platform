from dataclasses import FrozenInstanceError

import pytest

from pagination import Page, PageRequest, parse_pagination


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, PageRequest(1, 20)),
        ({"page": "2", "per_page": "50"}, PageRequest(2, 50)),
        ({"page": "0", "per_page": "21"}, PageRequest(1, 20)),
        ({"page": "-1", "per_page": "true"}, PageRequest(1, 20)),
        ({"page": "999999999999999999999", "per_page": "50"}, PageRequest(1, 50)),
        ({"page": True, "per_page": 50}, PageRequest(1, 50)),
    ],
)
def test_parse_pagination_uses_only_bounded_exact_safe_values(values, expected):
    assert parse_pagination(values) == expected


def test_page_contract_is_frozen_and_empty_page_is_exact():
    page = Page(items=(), page=1, per_page=20, total=0, total_pages=0)

    assert page == Page((), 1, 20, 0, 0)
    with pytest.raises(FrozenInstanceError):
        page.page = 2


@pytest.mark.parametrize(
    "factory",
    [
        lambda: PageRequest(True, 20),
        lambda: PageRequest(1, 10),
        lambda: Page([], 1, 20, 0, 0),
        lambda: Page((), True, 20, 0, 0),
        lambda: Page((), 1, 20, 1, 0),
        lambda: Page(("row",), 2, 20, 1, 1),
    ],
)
def test_page_contract_rejects_bool_non_exact_and_inconsistent_construction(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()
