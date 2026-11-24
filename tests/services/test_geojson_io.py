"""
Hermetic tests for the geospatial-file -> GeoJSON conversion (no GEE, no
credentials).

    .venv/bin/python -m pytest tests/services/test_geojson_io.py -v
"""
import json
import os
import tempfile
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from semente.services.geospatial.geojson_io import (
    SUPPORTED_EXTENSIONS,
    GeoFileError,
    UnsupportedFormatError,
    convert_geo_file_to_geojson,
    resolve_geo_filename,
    save_debug_json,
)


def _single_polygon_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                },
            }
        ],
    }


def _multi_polygon_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
                        [[[2, 2], [2, 3], [3, 3], [3, 2], [2, 2]]],
                    ],
                },
            }
        ],
    }


_KML = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>P1</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
-49.2,-16.6,0 -49.1,-16.6,0 -49.1,-16.5,0 -49.2,-16.5,0 -49.2,-16.6,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
<Placemark><name>P2</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
-49.0,-16.6,0 -48.9,-16.6,0 -48.9,-16.5,0 -49.0,-16.5,0 -49.0,-16.6,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""


def test_supported_extensions_match_old_intake():
    assert SUPPORTED_EXTENSIONS == {".zip", ".rar", ".kmz", ".kml", ".geojson", ".json"}


def test_geojson_passthrough_single_polygon():
    raw = json.dumps(_single_polygon_geojson()).encode()

    converted = convert_geo_file_to_geojson(raw, "property.geojson")
    parsed = json.loads(converted)

    assert parsed["type"] == "FeatureCollection"
    assert parsed["features"][0]["geometry"]["type"] == "Polygon"


def test_multi_polygon_becomes_multipolygon_geometry():
    raw = json.dumps(_multi_polygon_geojson()).encode()

    parsed = json.loads(convert_geo_file_to_geojson(raw, "property.json"))

    assert parsed["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_kml_conversion_collects_all_placemarks():
    parsed = json.loads(convert_geo_file_to_geojson(_KML.encode(), "map.kml"))

    geometry = parsed["features"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 2


def test_kmz_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        kml_path = os.path.join(tmp, "doc.kml")
        with open(kml_path, "w") as file:
            file.write(_KML)
        kmz_path = os.path.join(tmp, "map.kmz")
        with zipfile.ZipFile(kmz_path, "w") as archive:
            archive.write(kml_path, "doc.kml")

        content = open(kmz_path, "rb").read()

    parsed = json.loads(convert_geo_file_to_geojson(content, "map.kmz"))
    assert parsed["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_zipped_shapefile_conversion():
    with tempfile.TemporaryDirectory() as tmp:
        gdf = gpd.GeoDataFrame(
            {"name": ["p1"]},
            geometry=[Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])],
            crs="EPSG:4326",
        )
        gdf.to_file(os.path.join(tmp, "layer.shp"))

        zip_path = os.path.join(tmp, "shape.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            for name in os.listdir(tmp):
                if name.endswith((".shp", ".shx", ".dbf", ".prj", ".cpg")):
                    archive.write(os.path.join(tmp, name), name)

        content = open(zip_path, "rb").read()

    parsed = json.loads(convert_geo_file_to_geojson(content, "shape.zip"))
    assert parsed["features"][0]["geometry"]["type"] == "Polygon"


def test_reprojection_to_wgs84():
    # A square of 1km x 1km around lon -47.4 (UTM 23S, EPSG:31983).
    gdf = gpd.GeoDataFrame(
        {"name": ["p1"]},
        geometry=[Polygon([(250000, 7500000), (250000, 7501000), (251000, 7501000), (251000, 7500000)])],
        crs="EPSG:31983",
    )
    raw = gdf.to_json()

    parsed = json.loads(convert_geo_file_to_geojson(raw.encode(), "utm.geojson"))

    lon, lat = parsed["features"][0]["geometry"]["coordinates"][0][0]
    assert -47.5 < lon < -47.3
    assert -22.7 < lat < -22.5


def test_unsupported_extension_raises_unsupported_format_error():
    with pytest.raises(UnsupportedFormatError):
        convert_geo_file_to_geojson(b"anything", "notes.txt")


def test_file_without_polygon_raises_geofile_error():
    point_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Point", "coordinates": [0, 0]},
            },
        ],
    }
    with pytest.raises(GeoFileError):
        convert_geo_file_to_geojson(
            json.dumps(point_collection).encode(), "points.geojson"
        )


def test_overlapping_parts_are_not_merged_into_one_geometry():
    """Adjacent/overlapping paddocks must stay as separate polygon parts.

    Regression: calling make_valid on the whole MultiPolygon merged the parts
    into a single invalid shape, dropping the paddock boundaries (85 -> 5).
    """
    overlapping = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]],
                        [[[5, 5], [5, 15], [15, 15], [15, 5], [5, 5]]],
                        [[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]],
                    ],
                },
            }
        ],
    }

    parsed = json.loads(convert_geo_file_to_geojson(json.dumps(overlapping).encode(), "map.geojson"))

    # Every original part must survive: 3 paddocks + the (implicit) merge
    # never happens at conversion time, so the geometry keeps 3 parts.
    geometry = parsed["features"][0]["geometry"]
    assert geometry["type"] == "MultiPolygon"
    assert len(geometry["coordinates"]) == 3


def test_polygon_with_hole_keeps_its_interior_ring():
    polygon_with_hole = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]],
            [[2, 2], [2, 4], [4, 4], [4, 2], [2, 2]],
        ],
    }

    parsed = json.loads(
        convert_geo_file_to_geojson(json.dumps(polygon_with_hole).encode(), "hole.geojson")
    )

    geometry = parsed["features"][0]["geometry"]
    # One polygon with an exterior ring and one interior (hole) ring.
    assert geometry["type"] == "Polygon"
    assert len(geometry["coordinates"]) == 2


def test_resolve_geo_filename_passes_supported_through():
    assert resolve_geo_filename("shape.zip", b"") == "shape.zip"


def test_resolve_geo_filename_sniffs_magic_bytes():
    assert resolve_geo_filename("upload", b"PK\x03\x04rest") == "upload.zip"
    assert resolve_geo_filename("upload", b"Rar!\x1a\x07rest") == "upload.rar"
    kml = b'<?xml version="1.0"?><kml xmlns="..."></kml>'
    assert resolve_geo_filename("upload", kml) == "upload.kml"
    geojson = b'{"type": "FeatureCollection"}'
    assert resolve_geo_filename("upload", geojson) == "upload.geojson"


def test_resolve_geo_filename_leaves_unknown_alone():
    assert resolve_geo_filename("doc.pdf", b"%PDF-1.4") == "doc.pdf"


def test_save_debug_json_disabled_outside_dev(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    assert save_debug_json(b'{"type": "FeatureCollection"}', "x") is None


def test_save_debug_json_writes_file_in_development(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(
        "semente.services.geospatial.geojson_io._DEBUG_DIR", tmp_path / "geojson_debug"
    )

    path = save_debug_json(b'{"type": "FeatureCollection"}', "input_step_converted_x")

    assert path is not None and path.exists()
    assert path.suffix == ".json"
    assert "input_step_converted_x" in path.name
    assert json.loads(path.read_text())["type"] == "FeatureCollection"


def test_save_debug_json_accepts_dict(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setattr(
        "semente.services.geospatial.geojson_io._DEBUG_DIR", tmp_path / "geojson_debug"
    )

    path = save_debug_json(_multi_polygon_geojson(), "tool")

    assert path is not None and path.exists()


# ---------------------------------------------------------------------------
# polygon_labels: the source name of each polygon, aligned with the parts
# ---------------------------------------------------------------------------

def _zipped_shapefile(columns: dict, geometries: list) -> bytes:
    """Builds a zipped shapefile with the given attribute columns."""
    with tempfile.TemporaryDirectory() as tmp:
        gdf = gpd.GeoDataFrame(columns, geometry=geometries, crs="EPSG:4326")
        gdf.to_file(os.path.join(tmp, "layer.shp"))

        zip_path = os.path.join(tmp, "shape.zip")
        with zipfile.ZipFile(zip_path, "w") as archive:
            for name in os.listdir(tmp):
                if name.endswith((".shp", ".shx", ".dbf", ".prj", ".cpg")):
                    archive.write(os.path.join(tmp, name), name)

        return open(zip_path, "rb").read()


def _square(x: float) -> Polygon:
    return Polygon([(x, 0), (x, 1), (x + 1, 1), (x + 1, 0)])


def _labels(content: bytes, filename: str) -> list:
    parsed = json.loads(convert_geo_file_to_geojson(content, filename))
    return parsed["features"][0]["properties"]["polygon_labels"]


def test_kml_placemark_names_become_polygon_labels():
    assert _labels(_KML.encode(), "map.kml") == ["P1", "P2"]


def test_shapefile_label_column_is_case_insensitive():
    content = _zipped_shapefile({"NOME": ["A", "B"]}, [_square(0), _square(2)])

    assert _labels(content, "shape.zip") == ["A", "B"]


def test_shapefile_without_label_column_has_no_labels():
    content = _zipped_shapefile({"area": [1.5, 2.5]}, [_square(0), _square(2)])

    assert _labels(content, "shape.zip") == [None, None]


def test_empty_label_values_become_none():
    content = _zipped_shapefile(
        {"nome": ["A", None, ""]}, [_square(0), _square(2), _square(4)]
    )

    assert _labels(content, "shape.zip") == ["A", None, None]


def test_whole_number_labels_drop_the_decimal():
    content = _zipped_shapefile({"piquete": [1.0, 2.0]}, [_square(0), _square(2)])

    assert _labels(content, "shape.zip") == ["1", "2"]


def test_multipart_feature_repeats_its_label_per_part():
    from shapely.geometry import MultiPolygon

    content = _zipped_shapefile(
        {"nome": ["Duplo", "Simples"]},
        [MultiPolygon([_square(0), _square(3)]), _square(6)],
    )

    assert _labels(content, "shape.zip") == ["Duplo", "Duplo", "Simples"]


def test_polygon_labels_match_polygon_count():
    parsed = json.loads(convert_geo_file_to_geojson(_KML.encode(), "map.kml"))
    properties = parsed["features"][0]["properties"]

    assert len(properties["polygon_labels"]) == properties["polygon_count"]
