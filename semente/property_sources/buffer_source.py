"""Approximate-circle source. The circle is NOT a property boundary: it only stands in for one."""

from __future__ import annotations

import math
from typing import Optional

from semente.property_sources.candidate import GeometryOrigin, PropertyCandidate

DEFAULT_RADIUS_METERS = 500
_EARTH_RADIUS_M = 6_371_008.8
_VERTICES = 64


def _circle(lat: float, lon: float, radius_m: float) -> list:
    """Closed 64-vertex geodesic ring as MultiPolygon coordinates (not split at the antimeridian)."""
    phi1, lambda1, delta = math.radians(lat), math.radians(lon), radius_m / _EARTH_RADIUS_M
    ring = []
    for i in range(_VERTICES):
        theta = math.radians(360.0 * i / _VERTICES)
        sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
        lambda2 = lambda1 + math.atan2(
            math.sin(theta) * math.sin(delta) * math.cos(phi1), math.cos(delta) - math.sin(phi1) * sin_phi2
        )
        ring.append([(math.degrees(lambda2) + 180.0) % 360.0 - 180.0, math.degrees(math.asin(sin_phi2))])
    ring.append(list(ring[0]))
    return [[ring]]


class BufferSource:
    """One approximate circle of ``radius_m`` around the searched point (``search_radius_m`` is ignored)."""

    key = "buffer"

    def __init__(self, radius_m: float = DEFAULT_RADIUS_METERS):
        """Raises ValueError unless ``radius_m`` is a finite number > 0."""
        if not isinstance(radius_m, (int, float)) or not math.isfinite(radius_m) or radius_m <= 0:
            raise ValueError(f"BufferSource radius_m must be a finite number > 0, got {radius_m!r}.")
        self.radius_m = radius_m

    def find_by_point(self, latitude: float, longitude: float, search_radius_m: float = 2000) -> list[PropertyCandidate]:
        """Raises ValueError unless ``|latitude| <= 85`` and ``|longitude| <= 180`` (finite)."""
        if not (isinstance(latitude, (int, float)) and isinstance(longitude, (int, float))
                and math.isfinite(latitude) and math.isfinite(longitude)
                and abs(latitude) <= 85 and abs(longitude) <= 180):
            raise ValueError(f"Invalid coordinate: ({latitude}, {longitude}).")
        return [PropertyCandidate(
            candidate_id=f"circle-{latitude:.5f}-{longitude:.5f}-{self.radius_m:g}",
            origin=GeometryOrigin.APPROXIMATE_CIRCLE,
            source=self.key,
            geometry={"type": "MultiPolygon", "coordinates": _circle(latitude, longitude, self.radius_m)},
            area_ha=round(math.pi * self.radius_m ** 2 / 10_000.0, 2),
            distance_m=0.0,
            attributes={"radius_m": self.radius_m},
            warnings=["approximate_area"],
        )]

    def find_by_id(self, identifier: str) -> Optional[PropertyCandidate]:
        return None
