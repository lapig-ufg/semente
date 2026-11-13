import math

import pytest

from semente.property_sources import BufferSource, GeometryOrigin


def _ring(candidate):
    return candidate.geometry["coordinates"][0][0]


def test_single_circle_candidate():
    [candidate] = BufferSource().find_by_point(-15.78, -47.93, search_radius_m=10)
    assert candidate.origin is GeometryOrigin.APPROXIMATE_CIRCLE and candidate.source == "buffer"
    assert candidate.distance_m == 0 and candidate.warnings == ["approximate_area"]
    assert candidate.geometry["type"] == "MultiPolygon"
    assert candidate.candidate_id == "circle--15.78000--47.93000-500"
    assert candidate.attributes == {"radius_m": 500}
    assert candidate.area_ha == pytest.approx(math.pi * 500 ** 2 / 1e4, rel=0.01)
    assert BufferSource().find_by_id("x") is None


def test_ring_is_closed_64_vertices_at_radius_with_first_north():
    lat, lon, radius = -15.78, -47.93, 800
    ring = _ring(BufferSource(radius).find_by_point(lat, lon)[0])
    assert len(ring) == 65 and ring[0] == ring[-1]
    phi1 = math.radians(lat)
    for vlon, vlat in ring:
        phi2 = math.radians(vlat)
        a = math.sin((phi2 - phi1) / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(vlon - lon) / 2) ** 2
        assert 2 * 6_371_008.8 * math.asin(math.sqrt(a)) == pytest.approx(radius, rel=1e-6)
    assert ring[0][1] > lat and ring[0][0] == pytest.approx(lon, abs=1e-9)


@pytest.mark.parametrize("lat,lon", [(91, 0), (86, 0), (0, 181), (float("nan"), 0), (0, float("inf")), ("1", 0)])
def test_invalid_coordinate_raises(lat, lon):
    with pytest.raises(ValueError):
        BufferSource().find_by_point(lat, lon)


@pytest.mark.parametrize("radius", [0, -5, float("nan"), float("inf"), "500", None])
def test_invalid_radius_raises(radius):
    with pytest.raises(ValueError, match="radius_m"):
        BufferSource(radius)


@pytest.mark.parametrize("lon", [179.999, 180.0])
def test_antimeridian_longitudes_are_normalized(lon):
    ring = _ring(BufferSource(2000).find_by_point(0.0, lon)[0])
    assert all(-180 <= x < 180 for x, _ in ring)
