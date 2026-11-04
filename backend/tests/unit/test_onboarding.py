"""The two questions' rules (10 §5.1): the markup's bounds, the closed brand list, and what a skip or "אחר" sets."""

from decimal import Decimal

import pytest

from konboro.db import models as m
from konboro.services import onboarding as ob


@pytest.mark.parametrize("value", ["0", "0.25", "1", "5"])
def test_a_markup_up_to_500_percent(value: str) -> None:
    ob.check_markup(Decimal(value))


@pytest.mark.parametrize("value", ["-0.01", "5.0001", "NaN", "Infinity"])
def test_a_markup_out_of_bounds(value: str) -> None:
    with pytest.raises(ob.OnboardingError) as e:
        ob.check_markup(Decimal(value))
    assert e.value.field == "markup"


def test_brands_set_skip_and_other() -> None:
    row = m.TenantSettings(tenant_id="tnt_1", brand_preferences={"rcd": "ABB", "contactor": "Schneider"})
    ob.set_brands(row, {"circuit_breaker": "Hager", "rcd": None})
    assert row.brand_preferences == {"circuit_breaker": "Hager", "contactor": "Schneider"}
    ob.set_brands(row, {"circuit_breaker": "other"})
    assert row.brand_preferences == {"contactor": "Schneider"}  # "אחר" names no brand stage 5 could prefer


@pytest.mark.parametrize("brands", [{"contactor": "ABB"}, {"rcd": "Siemens"}, {"circuit_breaker": "abb"}])
def test_brands_from_the_closed_list_only(brands: dict[str, str | None]) -> None:
    with pytest.raises(ob.OnboardingError):
        ob.check_brands(brands)
