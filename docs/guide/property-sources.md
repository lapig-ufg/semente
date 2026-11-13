# Property Sources

A **property source** answers where candidate property boundaries come from:
which polygons lie around a coordinate, and which polygon belongs to an
identifier of the source (a registry number, for example). The contract is
**engine-free** and country-agnostic: it lives in `semente.property_sources`
and imports without the `geo` extra.

```python
from semente.property_sources import (
    PropertySource, PropertySourceError, PropertyCandidate, CandidateAttribute,
    GeometryOrigin, BufferSource,
    register_source, get_source, enabled_keys, enabled_sources,
)
```

## The contract

```python
class PropertySource(Protocol):          # runtime_checkable
    key: str

    def find_by_point(self, latitude, longitude, search_radius_m=2000) -> list[PropertyCandidate]: ...
    def find_by_id(self, identifier) -> PropertyCandidate | None: ...
```

- `find_by_point` returns candidates ordered by relevance (possibly empty).
- `find_by_id` returns the candidate of a source-specific identifier, or `None`.
- Both raise `PropertySourceError` when the source cannot answer.
- `search_radius_m` is the **search radius in meters** around the point. It is
  unrelated to the buffer radius of `BufferSource` (the protocol default is
  2000 m; the buffer circle is 500 m).

### `PropertyCandidate`

| Field | Description |
|---|---|
| `candidate_id` | Stable identifier inside the source. |
| `name` | Name given by the source, if any. |
| `origin` | `GeometryOrigin`: `registered_boundary`, `osm_landuse` (a generic land-use polygon; the name is historical), `user_polygon` or `approximate_circle`. |
| `source` | Key of the source. |
| `source_date` | Date of the source data (ISO), if known. |
| `geometry` | GeoJSON `Polygon` or `MultiPolygon` (lon, lat). Not shape-validated by the model. |
| `area_ha` | Area in hectares. |
| `distance_m` | Distance from the searched point (0 when inside). |
| `attributes` | `list[CandidateAttribute(key, value, unit)]`. |
| `license` | License and attribution of the data. |
| `warnings` | Neutral warning keys (see below). |

`type_key` is `origin.value`, and `to_session()` returns plain JSON (for
`session_state`). A candidate has no conversion to any app model: turning a
confirmed candidate into your own area or feature is the app's job.

### Errors

Two different kinds of failure exist:

- **Caller errors** raise `ValueError`: an invalid coordinate (the supported
  range is `|latitude| <= 85` and `|longitude| <= 180`) or an invalid radius.
- **Source failures** raise `PropertySourceError(kind, message)`, with a `kind`
  from `PropertySourceError.KINDS`:

| Kind | Meaning |
|---|---|
| `unavailable` | Service down or error response. |
| `timeout` | The service did not answer in time. |
| `not_found` | Unknown identifier. |
| `urban_area` | The point lies in a land use where no property candidate is offered. |

Return `[]` (or `None`) when nothing is found; raise only when the source
could not answer.

### Warnings

`warnings` are neutral keys, never user-facing text. The app maps them to its
own wording (and language). The built-in source emits `approximate_area`.

## The built-in `buffer` source

`BufferSource` (key `buffer`, default radius 500 m) returns one candidate: a
64-vertex geodesic circle around the point, as a `MultiPolygon`, with
`origin=approximate_circle`, `distance_m=0`, a `radius` attribute (in `m`) and
the warning `approximate_area`. `find_by_id` always returns `None`, and
`search_radius_m` is ignored. The constructor requires a finite `radius_m > 0`
and an invalid coordinate raises `ValueError`. Near the antimeridian the ring
is not split: longitudes are only normalized to [-180, 180).

> The circle is **not** a property boundary. It is an approximation around the
> point, offered when no real boundary is available. Apps must present it as
> such.

## Adapting to a country

A country plugs in its own registry by implementing the protocol and
registering it. Example over a hypothetical national registry:

```python
from semente.property_sources import (
    GeometryOrigin, PropertyCandidate, PropertySourceError, register_source,
)

# query_registry() and get_registry_row() are YOUR country's registry client
# (an HTTP API, a database, a file export). They are not part of Semente.


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
            candidate_id=row["registry_number"], name=row["owner_label"],
            origin=GeometryOrigin.REGISTERED_BOUNDARY, source=self.key,
            source_date=row["updated_at"], geometry=row["geojson"],
            area_ha=row["area_ha"], distance_m=row["distance_m"],
            license="national open data licence",
        )


register_source("registry", NationalRegistrySource)
```

Rules of thumb:

- `geometry` is GeoJSON in lon/lat (WGS84); `area_ha` comes from the source.
- `distance_m` is 0 when the point lies inside the polygon.
- Order candidates by relevance, best first.
- Raise `PropertySourceError` only when the source could not answer; return
  `[]` or `None` when it answered with nothing.
- Set your own timeouts on network calls and map them to `timeout`.
- Use `registered_boundary` only for official polygons, never approximations.

## Registry and configuration

| Function | Description |
|---|---|
| `register_source(key, factory)` | Registers (or replaces) a source; `factory` is a class or callable, called once, on demand. Re-registering drops the cached instance. |
| `get_source(key)` | Returns the shared instance; raises `KeyError` for an unknown key. |
| `enabled_keys(manifest=None)` | Keys of the enabled sources, in priority order. |
| `enabled_sources(manifest=None)` | Instances of the enabled sources; unknown keys are skipped with a warning. |

The enabled keys come from, in order of precedence:

1. the `SEMENTE_PROPERTY_SOURCES` environment variable (comma-separated;
   ignored when it holds only separators);
2. the `property_sources` list of the [manifest](manifest.md);
3. the default `["buffer"]`.

Without a `manifest` argument, the manifest is loaded from the usual path
(`SEMENTE_MANIFEST` or `./semente.yaml`). A missing file is silent; a file that
fails to load logs a warning and the default applies. Register your own
sources at import time of your domain, before calling `enabled_sources()`.

```yaml
property_sources: [registry, buffer]
```
