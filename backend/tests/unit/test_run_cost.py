"""A run's cost in dollars (01 §4.6 "עלות", S28c): each call priced from the list prices, in Decimal, the cache's
tokens at their own price; a model missing from the table priced as the dearest."""

from decimal import Decimal

from konboro.services import run_cost
from konboro.services.run_cost import call_cost, model_label, usd_text
from konboro_llm.types import Usage


def test_a_call_is_priced_per_million_tokens_in_decimal() -> None:
    # Sonnet 5.5: $2 in, $10 out per million
    cost = call_cost("claude-sonnet-5-5", Usage(1_000, 10_000))
    assert cost == Decimal("0.102000")
    assert isinstance(cost, Decimal)


def test_the_cache_has_its_own_prices() -> None:
    # Opus 5.5: a cache read is $0.20 a million, a 5-minute cache write 1.25 times the input ($5)
    assert call_cost("claude-opus-5-5", Usage(0, 0, cache_read_tokens=1_000_000)) == Decimal("0.200000")
    assert call_cost("claude-opus-5-5", Usage(0, 0, cache_write_tokens=1_000_000)) == Decimal("5.000000")


def test_haiku_costs_more_past_a_long_prompt() -> None:
    short = call_cost("claude-haiku-5-5", Usage(100_000, 0))
    long = call_cost("claude-haiku-5-5", Usage(100_001, 0))
    assert short == Decimal("0.010000")
    assert long > short * 4


def test_an_unknown_model_is_priced_as_the_dearest_and_bedrock_ids_are_known() -> None:
    usage = Usage(1_000_000, 0)
    assert call_cost("some-new-model", usage) == call_cost("claude-opus-5-5", usage)
    assert call_cost("anthropic.claude-haiku-5-5", usage) == call_cost("claude-haiku-5-5", usage)


def test_no_tokens_cost_nothing() -> None:
    assert call_cost("stand-in", Usage(0, 0)) == Decimal(0)


def test_the_breakdown_names_the_text_reading_by_what_it_does() -> None:
    assert model_label("ocr_transcription", "claude-sonnet-5-5") == "קריאת טקסט"
    assert model_label("page_classification", "claude-haiku-5-5") == "Haiku"
    assert model_label("symbol_detection", "anthropic.claude-opus-5-5") == "Opus"
    assert model_label("x", "fake-model") == "fake-model"


def test_dollars_to_the_cent() -> None:
    assert usd_text(Decimal("0.4449")) == "0.44"
    assert usd_text(Decimal(0)) == "0.00"


def test_the_list_prices_are_the_current_ones() -> None:
    """Changing a price is a decision: it moves what every run shows."""
    p = run_cost.PRICES
    assert (p["claude-haiku-5-5"].input, p["claude-haiku-5-5"].output) == (Decimal("0.10"), Decimal("0.50"))
    assert (p["claude-sonnet-5-5"].input, p["claude-sonnet-5-5"].output) == (Decimal("2.00"), Decimal("10.00"))
    assert (p["claude-opus-5-5"].input, p["claude-opus-5-5"].output) == (Decimal("4.00"), Decimal("20.00"))
