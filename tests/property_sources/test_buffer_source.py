"""BufferSource: one honest approximate circle around the point."""

import math

import pytest

from semente.property_sources import BufferSource, GeometryOrigin


def _ring(candidate):
    return candidate.geometry["coordinates"][0][0]


def test_single_circle_candidate():
    candidates = BufferSource().find_by_point(-15.78, -47.93)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.origin is GeometryOrigin.APPROXIMATE_CIRCLE
    assert candidate.source == "buffer"
    assert candidate.distance_m == 0
    assert candidate.warnings == ["approximate_area"]
    assert candidate.geometry["type"] == "MultiPolygon"
    assert candidate.candidate_id == "circle--15.78000--47.93000-500"
    assert [(a.key, a.value, a.unit) for a in candidate.attributes] == [("radius", 500, "m")]


def test_ring_has_64_vertices_and_closes():
    ring = _ring(BufferSource().find_by_point(10.0, 20.0)[0])
    assert len(ring) == 65
    assert ring[0] == ring[-1]


def test_area_matches_circle_within_one_percent():
    for radius in (500, 1500):
        candidate = BufferSource(radius).find_by_point(-15.78, -47.93)[0]
        expected = math.pi * radius ** 2 / 1e4
        assert candidate.area_ha == pytest.approx(expected, rel=0.01)


def test_default_radius_and_search_radius_ignored():
    assert BufferSource().radius_m == 500
    small = BufferSource().find_by_point(1.0, 2.0, search_radius_m=10)[0]
    large = BufferSource().find_by_point(1.0, 2.0, search_radius_m=99999)[0]
    assert small.geometry == large.geometry


def test_find_by_id_is_none():
    assert BufferSource().find_by_id("anything") is None


@pytest.mark.parametrize("lat,lon", [(91, 0), (86, 0), (0, 181), (float("nan"), 0), (0, float("inf"))])
def test_invalid_coordinate_raises(lat, lon):
    with pytest.raises(ValueError):
        BufferSource().find_by_point(lat, lon)


def test_non_positive_radius_raises():
    with pytest.raises(ValueError):
        BufferSource(0).find_by_point(0.0, 0.0)


def test_antimeridian_longitudes_are_normalized():
    ring = _ring(BufferSource(2000).find_by_point(0.0, 179.999)[0])
    assert all(-180 <= lon < 180 for lon, _ in ring)
    assert any(lon < 0 for lon, _ in ring) and any(lon > 0 for lon, _ in ring)


def test_longitude_180_is_valid():
    ring = _ring(BufferSource().find_by_point(0.0, 180.0)[0])
    assert all(-180 <= lon < 180 for lon, _ in ring)


@pytest.mark.parametrize("radius", [0, -5, float("nan"), float("inf"), "500", None])
def test_invalid_radius_rejected_at_construction(radius):
    with pytest.raises(ValueError, match="radius_m"):
        BufferSource(radius)


def test_vertices_lie_at_radius_and_first_is_north():
    lat, lon, radius = -15.78, -47.93, 800
    ring = _ring(BufferSource(radius).find_by_point(lat, lon)[0])
    phi1 = math.radians(lat)
    for vlon, vlat in ring:
        phi2 = math.radians(vlat)
        a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(vlon - lon) / 2) ** 2
        assert 2 * 6_371_008.8 * math.asin(math.sqrt(a)) == pytest.approx(radius, rel=1e-6)
    first_lon, first_lat = ring[0]
    assert first_lat > lat and first_lon == pytest.approx(lon, abs=1e-9)
