"""
Tests for fishing_common.schemas (Pydantic v2 validation).
"""
import pytest
from pydantic import ValidationError

from fishing_common.schemas import FishingAdviceResponse, FishingRequest


class TestFishingRequest:
    def test_valid_minimal(self):
        req = FishingRequest(lat=35.68, lon=139.77)
        assert req.lat == 35.68
        assert req.lon == 139.77
        assert req.target_species is None

    def test_valid_full(self):
        req = FishingRequest(
            lat=-33.87,
            lon=151.21,
            target_species="snapper",
            spot_type="offshore",
            start_at="2026-03-28T06:00:00Z",
        )
        assert req.target_species == "snapper"

    def test_lat_too_high(self):
        with pytest.raises(ValidationError) as exc_info:
            FishingRequest(lat=91.0, lon=0.0)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("lat",) for e in errors)

    def test_lat_too_low(self):
        with pytest.raises(ValidationError):
            FishingRequest(lat=-91.0, lon=0.0)

    def test_lon_too_high(self):
        with pytest.raises(ValidationError) as exc_info:
            FishingRequest(lat=0.0, lon=181.0)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("lon",) for e in errors)

    def test_lon_too_low(self):
        with pytest.raises(ValidationError):
            FishingRequest(lat=0.0, lon=-181.0)

    def test_boundary_values(self):
        """Edge values at ±90 / ±180 must be accepted."""
        FishingRequest(lat=90.0, lon=180.0)
        FishingRequest(lat=-90.0, lon=-180.0)

    def test_missing_lat(self):
        with pytest.raises(ValidationError) as exc_info:
            FishingRequest(lon=139.77)
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("lat",) for e in errors)

    def test_missing_lon(self):
        with pytest.raises(ValidationError):
            FishingRequest(lat=35.68)

    def test_extra_fields_ignored(self):
        """model_config extra='ignore' must silently drop unknown keys."""
        req = FishingRequest(lat=35.0, lon=139.0, unknown_field="should_be_ignored")
        assert not hasattr(req, "unknown_field")

    def test_model_validate_from_dict(self):
        data = {"lat": 35.0, "lon": 139.0, "target_species": "aji"}
        req = FishingRequest.model_validate(data)
        assert req.target_species == "aji"


class TestFishingAdviceResponse:
    def test_valid_response(self):
        resp = FishingAdviceResponse(
            summary="Good conditions",
            score={"value": 75, "label": "good"},
            season={"month": 4, "label": "spring"},
            best_windows=["06:00-08:00"],
            recommended_tactics=["bottom fishing"],
            risk_and_safety=[],
            evidence=["wave height < 1m"],
        )
        assert resp.score.value == 75
        assert resp.season.label == "spring"

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            FishingAdviceResponse(
                summary="x",
                score={"value": 150, "label": "impossible"},
                season={"month": 4, "label": "spring"},
            )

    def test_invalid_month(self):
        with pytest.raises(ValidationError):
            FishingAdviceResponse(
                summary="x",
                score={"value": 50, "label": "ok"},
                season={"month": 13, "label": "invalid"},
            )
