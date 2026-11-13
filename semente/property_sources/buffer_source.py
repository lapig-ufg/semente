"""Approximate-circle source: a buffer around the coordinate, honestly labeled.

It is the fallback when no real boundary is available. The circle is NOT a
property boundary: it is an approximation around the point, and its candidate
says so (origin ``approximate_circle``, warning ``approximate_area``).
"""

from __future__ import annotations

import math
from typing import Optional

from semente.property_sources._geodesy import circle_area_hectares, circle_multipolygon
from semente.property_sources.candidate import CandidateAttribute, GeometryOrigin, PropertyCandidate

DEFAULT_RADIUS_METERS = 500


class BufferSource:
    """Source that returns one circle around the searched point.

    The circle is not a property boundary; it only stands in for one when no
    registered or mapped polygon is available.

    Attributes:
        key (str): ``"buffer"``.
        radius_m (float): Radius of the circle in meters.
    """

    key = "buffer"

    def __init__(self, radius_m: float = DEFAULT_RADIUS_METERS):
        """Creates the source.

        Args:
            radius_m (float): Radius of the circle in meters (finite and > 0).

        Raises:
            ValueError: If ``radius_m`` is not a finite positive number.
        """
        if not isinstance(radius_m, (int, float)) or not math.isfinite(radius_m) or radius_m <= 0:
            raise ValueError(f"BufferSource radius_m must be a finite number > 0, got {radius_m!r}.")
        self.radius_m = radius_m

    def find_by_point(self, latitude: float, longitude: float, search_radius_m: float = 2000) -> list[PropertyCandidate]:
        """Returns one approximate circle of ``radius_m`` around the point.

        Args:
            latitude (float): Latitude in decimal degrees.
            longitude (float): Longitude in decimal degrees.
            search_radius_m (float): Unused; kept for the protocol.

        Returns:
            list[PropertyCandidate]: A single candidate with origin ``approximate_circle``,
            a 64-vertex MultiPolygon, ``distance_m`` 0, a ``radius`` attribute (m) and
            the warning ``approximate_area``.

        Raises:
            ValueError: If the coordinate is invalid (``|latitude| <= 85``, ``|longitude| <= 180``).
        """
        coordinates = circle_multipolygon(latitude, longitude, self.radius_m)
        return [PropertyCandidate(
            candidate_id=f"circle-{latitude:.5f}-{longitude:.5f}-{self.radius_m:g}",
            origin=GeometryOrigin.APPROXIMATE_CIRCLE,
            source=self.key,
            geometry={"type": "MultiPolygon", "coordinates": coordinates},
            area_ha=round(circle_area_hectares(self.radius_m), 2),
            distance_m=0.0,
            attributes=[CandidateAttribute(key="radius", value=self.radius_m, unit="m")],
            warnings=["approximate_area"],
        )]

    def find_by_id(self, identifier: str) -> Optional[PropertyCandidate]:
        """Circles have no identifiers: always None.

        Args:
            identifier (str): Ignored.

        Returns:
            None: Always.
        """
        return None
