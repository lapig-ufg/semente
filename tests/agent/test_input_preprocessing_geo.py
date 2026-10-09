"""
Tests for the Semente input pre-processing geospatial-file handling
(Semente-native File types, hermetic — no engine, no credentials).

    .venv/bin/python -m pytest tests/agent/test_input_preprocessing_geo.py -v
"""
import json
import os
import tempfile
import zipfile

import geopandas as gpd
from shapely.geometry import Polygon

from semente.core.semente_agent import Semente
from semente.manifest import Manifest
from semente.tools.types import File


def _agent() -> Semente:
    return Semente(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app"),
    )


def _zipped_shapefile_bytes() -> bytes:
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

        return open(zip_path, "rb").read()


def test_geo_file_is_converted_and_returned():
    user_text, geo_files = _agent()._input_preprocessing(
        input="Quero registrar minha propriedade",
        images=None,
        audio=None,
        files=[File(content=_zipped_shapefile_bytes(), name="shape.zip")],
    )

    assert user_text == "Quero registrar minha propriedade"
    assert geo_files and len(geo_files) == 1
    converted = geo_files[0]
    assert converted.format == "geojson"
    assert converted.mime_type == "application/json"
    assert converted.name == "shape.json"
    assert json.loads(converted.content.decode())["type"] == "FeatureCollection"
    # The raw document must not be carried over.
    assert all(file.format != "zip" for file in geo_files)


def test_invalid_geo_file_appends_error_note_and_no_file():
    user_text, geo_files = _agent()._input_preprocessing(
        input="Segue o arquivo",
        images=None,
        audio=None,
        files=[File(content=b"not a geo file", name="shape.zip")],
    )

    assert geo_files is None
    assert user_text
    assert "[ARQUIVO GEOESPACIAL]" in user_text


def test_non_geo_file_is_ignored():
    user_text, geo_files = _agent()._input_preprocessing(
        input="Olá",
        images=None,
        audio=None,
        files=[File(content=b"%PDF-1.4 ...", name="document.pdf")],
    )

    assert geo_files is None
    assert user_text == "Olá"


def test_zip_without_filename_is_detected_by_magic_bytes():
    user_text, geo_files = _agent()._input_preprocessing(
        input="",
        images=None,
        audio=None,
        files=[File(content=_zipped_shapefile_bytes())],
    )

    assert geo_files and geo_files[0].format == "geojson"


def test_text_passes_through_untouched():
    user_text, geo_files = _agent()._input_preprocessing(
        input="Olá, tudo bem?",
        images=None,
        audio=None,
        files=None,
    )

    assert user_text == "Olá, tudo bem?"
    assert geo_files is None