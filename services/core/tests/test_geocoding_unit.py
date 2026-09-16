"""Unit tests for three-state offline location classification (geocoding.py)."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rediska_core.domain.services.geocoding import classify_location


@pytest.fixture(autouse=True)
def home_settings():
    """Pin home coordinates (Philadelphia area) and threshold for all tests."""
    settings = SimpleNamespace(
        home_latitude=40.0,
        home_longitude=-75.2,
        location_near_threshold_miles=200,
    )
    with patch(
        "rediska_core.domain.services.geocoding.get_settings", return_value=settings
    ):
        yield settings


# =============================================================================
# Unclear: virtual, country-scale, timezone, un-geocodable
# =============================================================================


@pytest.mark.parametrize(
    "location",
    ["online", "Online", "remote", "anywhere", "US", "USA", "united states"],
)
def test_virtual_and_country_tokens_are_unclear(location):
    result = classify_location(location)
    assert result["location_state"] == "unclear"
    assert result["location_near"] is False
    assert result["geocoded"] is False


@pytest.mark.parametrize(
    "location", ["EST", "est", "CST", "MST", "PST", "EDT", "CDT", "MDT", "PDT"]
)
def test_timezone_strings_are_unclear_not_far(location):
    result = classify_location(location)
    assert result["location_state"] == "unclear"
    assert result["location_near"] is False


@pytest.mark.parametrize("location", [None, "", "   ", "xyzzy-nowhere-123"])
def test_empty_and_ungeocodable_are_unclear(location):
    result = classify_location(location)
    assert result["location_state"] == "unclear"
    assert result["distance_miles"] is None
    assert result["geocoded"] is False


# =============================================================================
# Concrete near / far unchanged
# =============================================================================


@pytest.mark.parametrize("location", ["PA", "philly", "NJ", "SEPA", "#PA"])
def test_concrete_near_locations(location):
    result = classify_location(location)
    assert result["location_state"] == "near"
    assert result["location_near"] is True
    assert result["geocoded"] is True
    assert result["distance_miles"] <= 200


@pytest.mark.parametrize("location", ["California", "UK", "Australia", "Texas"])
def test_concrete_far_locations(location):
    result = classify_location(location)
    assert result["location_state"] == "far"
    assert result["location_near"] is False
    assert result["geocoded"] is True
    assert result["distance_miles"] > 200


# =============================================================================
# Mixed / compound strings
# =============================================================================


def test_mixed_near_with_virtual_token_is_near():
    result = classify_location("NJ, online")
    assert result["location_state"] == "near"


def test_mixed_far_with_virtual_token_is_far():
    result = classify_location("#Europe #online")
    assert result["location_state"] == "far"


def test_mixed_near_part_wins_over_far_part():
    result = classify_location("PA / California")
    assert result["location_state"] == "near"


def test_mixed_all_far_parts_is_far():
    result = classify_location("Ontario, California")
    assert result["location_state"] == "far"


def test_mixed_no_concrete_parts_is_unclear():
    result = classify_location("online, anywhere, EST")
    assert result["location_state"] == "unclear"
    assert result["geocoded"] is False


def test_mixed_ungeocodable_with_virtual_is_unclear():
    result = classify_location("online, blorptown")
    assert result["location_state"] == "unclear"



class TestJoinedHashtagsAndRegions:
    """r/bdsmpersonals titles carry #newyork / #midwest style tokens."""

    def test_joined_state_name_geocodes(self):
        from rediska_core.domain.services.geocoding import _geocode

        assert _geocode("newyork") is not None
        assert _geocode("#newjersey")[2] == "us_state"
        assert _geocode("losangeles")[2] == "alias"

    def test_region_tokens_are_unclear(self):
        from rediska_core.domain.services.geocoding import classify_location

        assert classify_location("#midwest #usa")["location_state"] == "unclear"
        assert classify_location("eastcoast")["location_state"] == "unclear"
