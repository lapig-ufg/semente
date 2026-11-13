"""PropertyCandidate: neutral fields, type_key and JSON session form."""

import json

import pytest
from pydantic import ValidationError

from semente.property_sources import CandidateAttribute, GeometryOrigin, PropertyCandidate


def _candidate(**overrides):
    data = dict(
        candidate_id="c1", origin=GeometryOrigin.REGISTERED_BOUNDARY, source="registry",
        geometry={"type": "Polygon", "coordinates": []}, area_ha=12.5,
    )
    data.update(overrides)
    return PropertyCandidate(**data)


def test_defaults_and_type_key():
    candidate = _candidate()
    assert candidate.name is None and candidate.distance_m is None
    assert candidate.attributes == [] and candidate.warnings == []
    assert candidate.type_key == "registered_boundary"


def test_origin_values():
    assert {o.value for o in GeometryOrigin} == {
        "registered_boundary", "osm_landuse", "user_polygon", "approximate_circle",
    }


def test_to_session_is_plain_json():
    candidate = _candidate(
        attributes=[CandidateAttribute(key="radius", value=500, unit="m")],
        warnings=["approximate_area"], distance_m=0.0,
    )
    session = candidate.to_session()
    assert session["origin"] == "registered_boundary"
    assert session["attributes"] == [{"key": "radius", "value": 500, "unit": "m"}]
    assert json.loads(json.dumps(session)) == session


def test_no_feature_conversion():
    assert not hasattr(PropertyCandidate, "to_feature")


def test_geometry_is_required_but_not_shape_validated():
    with pytest.raises(ValidationError):
        PropertyCandidate(candidate_id="c", origin=GeometryOrigin.USER_POLYGON, source="s", area_ha=1.0)
    assert _candidate(geometry={}).geometry == {}
