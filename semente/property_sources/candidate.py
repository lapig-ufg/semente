"""Neutral schema of a property candidate: a polygon proposed as "the user's area".

A ``PropertyCandidate`` comes from a property source (a registry, a land-use
polygon, a polygon the user provides, or an approximate circle). The schema
knows nothing about how an app turns a confirmed candidate into its own
feature or area model; that conversion belongs to the app.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class GeometryOrigin(str, Enum):
    """Where the geometry of a candidate comes from.

    Attributes:
        REGISTERED_BOUNDARY: An official polygon from a registry (never an approximation).
        OSM_LANDUSE: A generic land-use polygon; the value keeps the historical
            ``osm_landuse`` name for compatibility and does not require OpenStreetMap.
        USER_POLYGON: A polygon provided by the user.
        APPROXIMATE_CIRCLE: A circle around a coordinate, not a real boundary.
    """

    REGISTERED_BOUNDARY = "registered_boundary"
    OSM_LANDUSE = "osm_landuse"
    USER_POLYGON = "user_polygon"
    APPROXIMATE_CIRCLE = "approximate_circle"


class CandidateAttribute(BaseModel):
    """One attribute of a candidate (a source tag or measurement).

    Attributes:
        key: Attribute name.
        value: Attribute value (any JSON-serializable type).
        unit: Optional unit of ``value`` (for example ``m``).
    """

    key: str
    value: Any
    unit: Optional[str] = None


class PropertyCandidate(BaseModel):
    """A candidate boundary for the area the user wants to register.

    ``warnings`` holds neutral keys (for example ``approximate_area``) that the
    app translates into user-facing text. The model does not validate that
    ``geometry`` is a well-formed GeoJSON polygon; sources are responsible for it.

    Attributes:
        candidate_id: Stable identifier inside the source.
        name: Name given by the source, if any.
        origin: Kind of geometry.
        source: Key of the property source.
        source_date: Date of the source data (ISO), if known.
        geometry: GeoJSON Polygon or MultiPolygon in lon/lat.
        area_ha: Area in hectares.
        distance_m: Distance from the searched point in meters (0 when inside).
        attributes: Source attributes.
        license: License and attribution of the data.
        warnings: Neutral warning keys.
    """

    candidate_id: str = Field(..., description="Stable identifier of the candidate inside its source.")
    name: Optional[str] = Field(default=None, description="Name given by the source, if any.")
    origin: GeometryOrigin = Field(..., description="Kind of geometry.")
    source: str = Field(..., description="Key of the property source.")
    source_date: Optional[str] = Field(default=None, description="Date of the source data (ISO), if known.")
    geometry: dict = Field(..., description="GeoJSON Polygon or MultiPolygon (lon, lat).")
    area_ha: float = Field(..., description="Area in hectares.")
    distance_m: Optional[float] = Field(default=None, description="Distance from the searched point in meters (0 when inside).")
    attributes: list[CandidateAttribute] = Field(default_factory=list, description="Source attributes.")
    license: Optional[str] = Field(default=None, description="License and attribution of the data.")
    warnings: list[str] = Field(default_factory=list, description="Neutral warning keys for the app to explain.")

    @property
    def type_key(self) -> str:
        """Neutral key of the geometry kind: the value of ``origin``."""
        return self.origin.value

    def to_session(self) -> dict:
        """Returns the JSON-serializable form (for example for ``session_state``).

        Returns:
            dict: The candidate as plain JSON types (enums as their values).
        """
        return json.loads(self.model_dump_json())
