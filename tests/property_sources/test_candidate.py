import json

import pytest
from pydantic import ValidationError

from semente.property_sources import GeometryOrigin, PropertyCandidate


def _candidate(**extra):
    return PropertyCandidate(
        candidate_id="c1", origin=GeometryOrigin.REGISTERED_BOUNDARY, source="registry",
        geometry={"type": "Polygon", "coordinates": []}, area_ha=12.5, **extra,
    )


def test_defaults_and_json_dump():
    candidate = _candidate(attributes={"radius_m": 500}, warnings=["approximate_area"])
    assert candidate.name is None and candidate.distance_m is None
    dumped = candidate.model_dump(mode="json")
    assert dumped["origin"] == "registered_boundary" and dumped["attributes"] == {"radius_m": 500}
    assert json.loads(json.dumps(dumped)) == dumped


def test_geometry_required_but_not_shape_validated():
    with pytest.raises(ValidationError):
        PropertyCandidate(candidate_id="c", origin=GeometryOrigin.USER_POLYGON, source="s", area_ha=1.0)
    assert _candidate().origin.value == "registered_boundary"
