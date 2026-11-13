# Property Sources

A **property source** answers where candidate property boundaries come from:
which polygons lie around a coordinate, and which one belongs to a
source-specific identifier. The contract in `semente.property_sources` is
engine-free, country-agnostic and imports without the `geo` extra.

## Contract

```python
class PropertySource(Protocol):          # runtime_checkable
    key: str
    def find_by_point(self, latitude, longitude, search_radius_m=2000) -> list[PropertyCandidate]: ...
    def find_by_id(self, identifier) -> PropertyCandidate | None: ...
```

`find_by_point` returns candidates best first (possibly empty); `search_radius_m`
is a search radius in meters, unrelated to the buffer radius below.
`find_by_id` returns `None` when the identifier does not exist.

## Candidate

`PropertyCandidate` fields: `candidate_id`, `origin`, `source`, `geometry`
(GeoJSON Polygon/MultiPolygon, lon/lat WGS84, shape not validated), `area_ha`,
plus optional `name`, `source_date`, `distance_m` (0 when the point is inside),
`attributes` (dict; put the unit in the key, e.g. `radius_m`), `license` and
`warnings` (neutral keys the app turns into text).

`GeometryOrigin`: `registered_boundary` (official polygons only, never
approximations), `osm_landuse` (a generic land-use polygon; the name is
historical), `user_polygon`, `approximate_circle`. Convert a confirmed
candidate into your own model in the app; serialize with `model_dump(mode="json")`.

## Errors

- Invalid input (coordinate outside `|lat| <= 85`, `|lon| <= 180`, or an invalid
  radius) raises `ValueError`.
- A source that cannot answer raises `PropertySourceError(kind, message)` with
  `kind` in `unavailable`, `timeout`, `not_found` or `urban_area`.
- Return `[]` or `None` when the source answered with nothing.

## Built-in `buffer` source

`BufferSource` (key `buffer`, radius 500 m by default, finite and > 0) returns one
candidate: a 64-vertex geodesic circle as a `MultiPolygon`, `approximate_circle`,
`distance_m=0`, attribute `radius_m` and warning `approximate_area`.
`find_by_id` is always `None`. The ring is not split at the antimeridian
(longitudes are only normalized).

> The circle is **not** a property boundary. It only stands in for one when no
> real boundary is available; apps must present it as such.

## Adapting to a country

Implement the protocol over your registry and register it. Set your own network
timeouts and map failures to `PropertySourceError`:

```python
from semente.property_sources import (
    GeometryOrigin, PropertyCandidate, PropertySourceError, register_source,
)

# query_registry() and get_registry_row() are YOUR country's registry client; not part of Semente.


class NationalRegistrySource:
    key = "registry"

    def find_by_point(self, latitude, longitude, search_radius_m=2000):
        try:
            rows = query_registry(lat=latitude, lon=longitude, radius=search_radius_m, timeout=10)
        except TimeoutError as exc:
            raise PropertySourceError("timeout", str(exc)) from exc
        except OSError as exc:
            raise PropertySourceError("unavailable", str(exc)) from exc
        return [self._to_candidate(row) for row in rows]

    def find_by_id(self, identifier):
        try:
            row = get_registry_row(identifier, timeout=10)
        except TimeoutError as exc:
            raise PropertySourceError("timeout", str(exc)) from exc
        except OSError as exc:
            raise PropertySourceError("unavailable", str(exc)) from exc
        return None if row is None else self._to_candidate(row)

    def _to_candidate(self, row):
        return PropertyCandidate(
            candidate_id=row["registry_number"], origin=GeometryOrigin.REGISTERED_BOUNDARY,
            source=self.key, source_date=row["updated_at"], geometry=row["geojson"],
            area_ha=row["area_ha"], distance_m=row["distance_m"],
        )


register_source("registry", NationalRegistrySource)
```

## Registry and configuration

`register_source(key, factory)` registers (or replaces) a source; the instance is
created on demand and shared. `get_source(key)` raises `KeyError` for unknown keys.
`enabled_keys(manifest=None)` and `enabled_sources(manifest=None)` return the
enabled sources in priority order, from:

1. the `SEMENTE_PROPERTY_SOURCES` environment variable (comma-separated; ignored if it holds only separators);
2. `property_sources` in the [manifest](manifest.md);
3. the default `["buffer"]`.

Without a `manifest`, it is read from `SEMENTE_MANIFEST` or `./semente.yaml` (missing:
silent; broken: a logged warning). Unknown keys are skipped with a warning. Register
your sources when your domain is imported.

```yaml
property_sources: [registry, buffer]
```
