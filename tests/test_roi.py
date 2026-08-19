from decimal import Decimal

from assessment.contracts import Scenario, ServicePackage
from assessment.roi import calculate_roi


RANGES = {
    "headcount": {"mid": (10, 13, 16), "open_plus": (50, 75, 100)},
    "monthly_hours": {"mid": (40, 50, 60)},
    "monthly_cost": {"mid": (9000, 11500, 14000)},
    "loss_factor": {"mid": ("0.05", "0.10", "0.15")},
    "budget": {"mid": (50000, 125000, 200000)},
}
MID_CHOICES = {
    "headcount": "mid",
    "monthly_hours": "mid",
    "monthly_cost": "mid",
    "loss_factor": "mid",
    "budget": "mid",
}


def scenario_profile(**overrides):
    values = {
        "efficiency": ("0.10", "0.20", "0.30"),
        "loss_improvement": ("0.10", "0.20", "0.30"),
        "annual_support_rate": ("0.08", "0.10", "0.12"),
    }
    values.update(overrides)
    return Scenario(
        code="scenario",
        category_code="pilot",
        branch_codes=("manufacturing",),
        department_codes=("production",),
        pain_codes=("pain",),
        minimum_scores={},
        integration_level="low",
        budget_codes=("mid",),
        min_weeks=1,
        max_weeks=2,
        efficiency=tuple(Decimal(value) for value in values["efficiency"]),
        loss_improvement=tuple(
            Decimal(value) for value in values["loss_improvement"]
        ),
        annual_support_rate=tuple(
            Decimal(value) for value in values["annual_support_rate"]
        ),
        risk_codes=(),
        service_code="service",
        sort_order=1,
    )


SERVICE = ServicePackage(
    code="service",
    category="pilot",
    public_name="Service",
    min_budget=Decimal("50000"),
    max_budget=Decimal("200000"),
    min_weeks=1,
    max_weeks=2,
    deliverables=(),
    implementation_steps=(),
    prerequisites=(),
    not_included=(),
    acceptance=(),
    support_days=30,
)


def test_midpoint_roi_uses_174_hour_loaded_cost_and_three_year_formula():
    result = calculate_roi(MID_CHOICES, RANGES, scenario_profile(), SERVICE)
    expected_hourly = Decimal("11500") / Decimal("174")
    expected_current = Decimal("13") * Decimal("50") * Decimal("12") * expected_hourly

    assert result.midpoint.current_annual_cost == expected_current.quantize(Decimal("0.01"))
    assert result.midpoint.payback_months > 0
    assert result.midpoint.three_year_net == (
        result.midpoint.annual_savings * Decimal("3")
        - result.midpoint.initial_investment
        - result.midpoint.three_year_support
    )


def test_roi_uses_three_exact_bands_and_finite_upper_bound_for_open_range():
    choices = {**MID_CHOICES, "headcount": "open_plus"}
    result = calculate_roi(choices, RANGES, scenario_profile(), SERVICE)

    assert result.conservative.band_code == "conservative"
    assert result.midpoint.band_code == "midpoint"
    assert result.ideal.band_code == "ideal"
    assert result.ideal.current_annual_cost == (
        Decimal("100") * Decimal("60") * Decimal("12")
        * Decimal("14000") / Decimal("174")
    ).quantize(Decimal("0.01"))
    assert result.conservative.initial_investment == Decimal("50000.00")
    assert result.midpoint.initial_investment == Decimal("125000.00")
    assert result.ideal.initial_investment == Decimal("200000.00")


def test_annual_savings_are_ordered_for_ordered_inputs():
    result = calculate_roi(MID_CHOICES, RANGES, scenario_profile(), SERVICE)

    assert (
        result.conservative.annual_savings
        <= result.midpoint.annual_savings
        <= result.ideal.annual_savings
    )


def test_zero_savings_has_no_payback():
    profile = scenario_profile(
        efficiency=("0", "0", "0"), loss_improvement=("0", "0", "0")
    )

    result = calculate_roi(MID_CHOICES, RANGES, profile, SERVICE)

    assert result.conservative.payback_months is None
    assert result.midpoint.payback_months is None
    assert result.ideal.payback_months is None


def test_negative_savings_are_clamped_for_display():
    profile = scenario_profile(
        efficiency=("-0.10", "-0.20", "-0.30"),
        loss_improvement=("-0.10", "-0.20", "-0.30"),
    )

    result = calculate_roi(MID_CHOICES, RANGES, profile, SERVICE)

    for band in (result.conservative, result.midpoint, result.ideal):
        assert band.labor_savings == Decimal("0.00")
        assert band.loss_savings == Decimal("0.00")
        assert band.annual_savings == Decimal("0.00")
        assert band.payback_months is None


def test_roi_values_are_decimals_and_money_is_rounded_half_up():
    result = calculate_roi(MID_CHOICES, RANGES, scenario_profile(), SERVICE)

    assert isinstance(result.midpoint.current_annual_cost, Decimal)
    assert result.midpoint.current_annual_cost.as_tuple().exponent == -2
    assert result.midpoint.payback_months.as_tuple().exponent == -1
