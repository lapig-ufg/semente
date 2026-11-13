"""Private pure-Python geodesic circle (no projection or geometry library).

Builds the ring of a circle on a sphere as the geodesic destination points at
evenly spaced bearings. Accurate to well under 1% for the short radii (a few
kilometers) used by approximate property areas.
"""

from __future__ import annotations

import math

EARTH_RADIUS_METERS = 6_371_008.8
CIRCLE_VERTICES = 64
# Contract decision: the supported range is |lat| <= 85 and |lon| <= 180.
MAX_ABS_LATITUDE = 85
MAX_ABS_LONGITUDE = 180
_SQUARE_METERS_PER_HECTARE = 10_000.0


def normalize_longitude(longitude: float) -> float:
    """Wraps a longitude into the [-180, 180) degree range.

    Args:
        longitude (float): Longitude in decimal degrees (any value).

    Returns:
        float: The equivalent longitude in [-180, 180).
    """
    return (longitude + 180.0) % 360.0 - 180.0


def is_valid_coordinate(latitude: float, longitude: float) -> bool:
    """Checks that a coordinate is finite and inside the supported range.

    Args:
        latitude (float): Latitude in decimal degrees.
        longitude (float): Longitude in decimal degrees.

    Returns:
        bool: True when both are finite numbers with ``|latitude| <= 85`` and
        ``|longitude| <= 180``; False otherwise (including non-numeric values).
    """
    try:
        return (
            math.isfinite(latitude) and math.isfinite(longitude)
            and abs(latitude) <= MAX_ABS_LATITUDE
            and abs(longitude) <= MAX_ABS_LONGITUDE
        )
    except TypeError:
        return False


def destination_point(latitude: float, longitude: float, bearing: float, distance: float) -> tuple[float, float]:
    """Computes the point reached from a coordinate along a bearing (spherical direct geodesic).

    Args:
        latitude (float): Start latitude in decimal degrees.
        longitude (float): Start longitude in decimal degrees.
        bearing (float): Initial bearing in degrees clockwise from north.
        distance (float): Distance to travel in meters.

    Returns:
        tuple[float, float]: ``(latitude, longitude)`` with the longitude in [-180, 180).
    """
    phi1 = math.radians(latitude)
    lambda1 = math.radians(longitude)
    theta = math.radians(bearing)
    delta = distance / EARTH_RADIUS_METERS
    sin_phi2 = math.sin(phi1) * math.cos(delta) + math.cos(phi1) * math.sin(delta) * math.cos(theta)
    phi2 = math.asin(sin_phi2)
    lambda2 = lambda1 + math.atan2(
        math.sin(theta) * math.sin(delta) * math.cos(phi1),
        math.cos(delta) - math.sin(phi1) * sin_phi2,
    )
    return math.degrees(phi2), normalize_longitude(math.degrees(lambda2))


def circle_area_hectares(radius_m: float) -> float:
    """Returns the area of a circle in hectares (pi * r^2 / 10^4).

    Args:
        radius_m (float): Radius in meters.

    Returns:
        float: Area in hectares.
    """
    return math.pi * radius_m ** 2 / _SQUARE_METERS_PER_HECTARE


def circle_multipolygon(latitude: float, longitude: float, radius_m: float, vertices: int = CIRCLE_VERTICES) -> list:
    """Builds a closed circular ring around a coordinate as GeoJSON MultiPolygon coordinates.

    Args:
        latitude (float): Center latitude in decimal degrees.
        longitude (float): Center longitude in decimal degrees.
        radius_m (float): Radius in meters (must be > 0).
        vertices (int): Number of distinct vertices (>= 3); the first is repeated at the end.

    Returns:
        list: ``[[[[lon, lat], ...]]]`` (one polygon, one ring, closed). Near the
        antimeridian the ring is not split: longitudes are only normalized to
        [-180, 180), so a circle crossing it has vertices on both sides.

    Raises:
        ValueError: If the coordinate is invalid, ``radius_m`` is not positive or ``vertices`` < 3.
    """
    if not is_valid_coordinate(latitude, longitude):
        raise ValueError(f"Invalid coordinate: ({latitude}, {longitude}).")
    if not radius_m > 0:
        raise ValueError(f"Radius must be positive, got {radius_m}.")
    if vertices < 3:
        raise ValueError(f"A ring needs at least 3 vertices, got {vertices}.")
    ring = []
    for i in range(vertices):
        lat, lon = destination_point(latitude, longitude, 360.0 * i / vertices, radius_m)
        ring.append([lon, lat])
    ring.append(list(ring[0]))
    return [[ring]]
