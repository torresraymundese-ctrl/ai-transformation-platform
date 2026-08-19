"""Pure Decimal-based three-band return-on-investment calculations."""

from collections.abc import Mapping, Sequence
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .contracts import RoiBand, RoiResult


LOADED_MONTH_HOURS = Decimal("174")
MONEY = Decimal("0.01")
PAYBACK_MONTH = Decimal("0.1")
ZERO = Decimal("0")
_BANDS = (("conservative", 0), ("midpoint", 1), ("ideal", 2))
_ROI_GROUPS = ("headcount", "monthly_hours", "monthly_cost", "loss_factor", "budget")


def money(value: Decimal) -> Decimal:
    """Round a currency value to cents using ordinary financial rounding."""
    return _decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def calculate_band(
    band_code: str,
    headcount: Decimal,
    monthly_hours: Decimal,
    monthly_cost: Decimal,
    loss_factor: Decimal,
    efficiency: Decimal,
    loss_improvement: Decimal,
    investment: Decimal,
    support_rate: Decimal,
) -> RoiBand:
    """Calculate one ROI band without any persistence or application dependencies."""
    hourly = monthly_cost / LOADED_MONTH_HOURS
    current = headcount * monthly_hours * Decimal(12) * hourly
    labor_savings = current * efficiency
    loss_savings = current * loss_factor * loss_improvement
    annual_savings = max(ZERO, labor_savings + loss_savings)
    payback = (
        None
        if annual_savings == ZERO
        else (investment / annual_savings * Decimal(12)).quantize(PAYBACK_MONTH)
    )
    annual_support = investment * support_rate
    net = annual_savings * Decimal(3) - investment - annual_support * Decimal(3)
    return RoiBand(
        band_code=band_code,
        current_annual_cost=money(current),
        labor_savings=money(labor_savings),
        loss_savings=money(loss_savings),
        annual_savings=money(annual_savings),
        initial_investment=money(investment),
        annual_support=money(annual_support),
        payback_months=payback,
        three_year_support=money(annual_support * Decimal(3)),
        three_year_net=money(net),
    )


def calculate_roi(
    choices: Mapping[str, str],
    option_ranges: Mapping[str, Mapping[str, Sequence[Any]]],
    roi_profile: Any,
    service_package: Any,
) -> RoiResult:
    """Calculate conservative, midpoint, and ideal ROI bands.

    ``option_ranges`` contains finite ``(low, midpoint, high)`` values for
    each selected choice code.  ``roi_profile`` may be a Scenario-like object
    or a mapping exposing the three coefficient triples.
    """
    values = {
        group: _selected_range(option_ranges, group, choices[group])
        for group in _ROI_GROUPS
    }
    investments = (
        _decimal(service_package.min_budget),
        (
            _decimal(service_package.min_budget)
            + _decimal(service_package.max_budget)
        ) / Decimal(2),
        _decimal(service_package.max_budget),
    )
    efficiencies = _profile_triple(roi_profile, "efficiency")
    loss_improvements = _profile_triple(roi_profile, "loss_improvement")
    support_rates = _profile_triple(roi_profile, "annual_support_rate")

    bands = tuple(
        calculate_band(
            band_code,
            _decimal(values["headcount"][index]),
            _decimal(values["monthly_hours"][index]),
            _decimal(values["monthly_cost"][index]),
            _decimal(values["loss_factor"][index]),
            efficiencies[index],
            loss_improvements[index],
            investments[index],
            support_rates[index],
        )
        for band_code, index in _BANDS
    )
    return RoiResult(
        conservative=bands[0], midpoint=bands[1], ideal=bands[2]
    )


def _selected_range(
    option_ranges: Mapping[str, Mapping[str, Sequence[Any]]],
    group: str,
    code: str,
) -> Sequence[Any]:
    group_ranges = option_ranges[group]
    return group_ranges[code]


def _profile_triple(profile: Any, name: str) -> tuple[Decimal, Decimal, Decimal]:
    values = getattr(profile, name, None)
    if values is None:
        values = profile[name]
    return tuple(_decimal(value) for value in values)  # type: ignore[return-value]


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))
