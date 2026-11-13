"""PropertySource protocol and PropertySourceError."""

from semente.property_sources import BufferSource, PropertySource, PropertySourceError


class _Complete:
    key = "complete"

    def find_by_point(self, latitude, longitude, search_radius_m=2000):
        return []

    def find_by_id(self, identifier):
        return None


class _Incomplete:
    key = "incomplete"

    def find_by_point(self, latitude, longitude, search_radius_m=2000):
        return []


def test_structural_conformance():
    assert isinstance(_Complete(), PropertySource)
    assert isinstance(BufferSource(), PropertySource)


def test_missing_method_does_not_satisfy():
    assert not isinstance(_Incomplete(), PropertySource)


def test_error_kind_and_kinds():
    assert PropertySourceError.KINDS == ("unavailable", "timeout", "not_found", "urban_area")
    error = PropertySourceError("timeout", "slow upstream")
    assert error.kind == "timeout" and str(error) == "slow upstream"
    assert str(PropertySourceError("not_found")) == "not_found"
