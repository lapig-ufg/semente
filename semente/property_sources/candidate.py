"""A polygon proposed to the user as "their area", from any property source."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class GeometryOrigin(str, Enum):
    """Kind of geometry; ``osm_landuse`` is just the historical name of a generic land-use polygon."""

    REGISTERED_BOUNDARY = "registered_boundary"
    OSM_LANDUSE = "osm_landuse"
    USER_POLYGON = "user_polygon"
    APPROXIMATE_CIRCLE = "approximate_circle"


class PropertyCandidate(BaseModel):
    """A candidate boundary; ``warnings`` are neutral keys the app turns into text.

    ``geometry`` is GeoJSON (lon/lat); its shape is not validated. Put units in
    ``attributes`` keys (for example ``radius_m``).
    """

    candidate_id: str
    origin: GeometryOrigin
    source: str
    geometry: dict
    area_ha: float
    name: Optional[str] = None
    source_date: Optional[str] = None
    distance_m: Optional[float] = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    license: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
