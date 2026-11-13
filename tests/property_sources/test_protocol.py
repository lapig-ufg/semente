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
    assert not isinstance(_Incomplete(), PropertySource)


def test_error_kind():
    assert PropertySourceError.KINDS == ("unavailable", "timeout", "not_found", "urban_area")
    error = PropertySourceError("timeout", "slow")
    assert error.kind == "timeout" and str(error) == "slow"
    assert str(PropertySourceError("not_found")) == "not_found"
