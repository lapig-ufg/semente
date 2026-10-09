"""Conversion of geospatial documents to a single GeoJSON ``FeatureCollection``.

Engine-neutral port of the Pasto Legal geo intake: handles the user-facing
formats

    - ``.zip`` (shapefile or any vector file inside)
    - ``.rar`` (shapefile or any vector file inside)
    - ``.kmz`` / ``.kml``
    - ``.geojson`` / ``.json`` (pass-through)

The output is always a GeoJSON ``FeatureCollection`` with a single feature
whose geometry is a ``Polygon`` (one polygon) or ``MultiPolygon`` (several
polygons), reprojected to EPSG:4326.

Depends on the optional ``geo`` extra (geopandas, shapely, pyproj, rarfile);
``geopandas_import_available()`` lets callers degrade gracefully when it is
absent.

External interface:
    convert_geo_file_to_geojson  -- bytes of any supported file to GeoJSON bytes
    resolve_geo_filename         -- filename with a supported extension (sniffing)
    save_debug_json              -- best-effort debug dump under tmp/ (dev only)
    GeoFileError                 -- user-facing conversion failure
    UnsupportedFormatError       -- not a geo-intake format (silently ignorable)
"""

import json
import os
import re
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union

from semente.logging import log_error, log_warning

_HECTARES_PER_SQUARE_METER = 1.0 / 10_000.0
_WGS84_EPSG = 4326

# Extensions accepted at intake and converted here.
SUPPORTED_EXTENSIONS = {".zip", ".rar", ".kmz", ".kml", ".geojson", ".json"}

# Vector extensions looked up inside archives.
_ARCHIVE_VECTOR_EXTENSIONS = {".shp", ".kml", ".geojson", ".json", ".gpkg"}

# Attribute columns (case-insensitive, in priority order) that may carry the
# name of each polygon in the source file.
_LABEL_COLUMNS = ("name", "nome", "piquete", "label")


class GeoFileError(ValueError):
    """Raised when a supported file cannot be converted to a usable GeoJSON."""


class UnsupportedFormatError(GeoFileError):
    """Raised when the file format is not a supported geo-intake format."""


def geopandas_import_available() -> bool:
    """Whether the geo stack (geopandas + shapely) is importable."""
    try:
        import geopandas  # noqa: F401
        import shapely  # noqa: F401

        return True
    except ImportError:
        return False


_DEBUG_DIR = Path.cwd() / "tmp" / "geojson_debug"


def debug_enabled() -> bool:
    """Whether the geojson debug dumps are enabled (non-production env)."""
    return os.getenv("APP_ENV", "").lower() in ("development", "dev", "stagging", "staging")


def save_debug_json(payload: Union[bytes, str, dict], label: str) -> Path | None:
    """Saves a GeoJSON payload under ``tmp/geojson_debug`` for debugging.

    Best-effort: any failure only logs a warning and never breaks the flow.
    Disabled outside development/staging environments.

    Args:
        payload: Raw bytes, string or parsed mapping to write.
        label: Short description included in the filename.

    Returns:
        The written path, or None when disabled or on failure.
    """
    if not debug_enabled():
        return None

    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)

        if isinstance(payload, dict):
            text = json.dumps(payload, ensure_ascii=False)
        elif isinstance(payload, (bytes, bytearray)):
            text = bytes(payload).decode("utf-8", errors="replace")
        else:
            text = str(payload)

        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "geojson"
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_label}.json"
        path = _DEBUG_DIR / filename
        path.write_text(text, encoding="utf-8")
        return path
    except Exception as error:  # pragma: no cover - defensive
        log_warning(f"geojson_io: failed to save debug json ({label}): {error}")
        return None


_ZIP_MAGIC = b"PK\x03\x04"
_RAR_MAGIC = b"Rar!\x1a\x07"


def _sniff_extension(content: bytes) -> str | None:
    """Detects a supported geo extension from the file magic bytes."""
    if content.startswith(_ZIP_MAGIC):
        return ".zip"
    if content.startswith(_RAR_MAGIC):
        return ".rar"
    head = content[:512].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<kml"):
        return ".kml"
    if head.startswith(b"{") or head.startswith(b"["):
        return ".geojson"
    return None


def resolve_geo_filename(filename: str, content: bytes) -> str:
    """Returns a filename with a supported extension, sniffing when needed."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in SUPPORTED_EXTENSIONS:
        return filename

    sniffed = _sniff_extension(content)
    if sniffed is None:
        return filename

    stem = Path(filename).stem if filename else "upload"
    return f"{stem}{sniffed}"


# =====================================================================
# Reading and normalization (lazy geopandas/shapely imports)
# =====================================================================


def _polygon_parts(geometry) -> List["Polygon"]:  # noqa: F821
    """Recursively extracts the polygonal parts of a shapely geometry."""
    import shapely

    if geometry is None or geometry.is_empty:
        return []

    geom_type = geometry.geom_type
    if geom_type == "Polygon":
        return [geometry]
    if geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if geom_type == "GeometryCollection":
        parts: List[Polygon] = []
        for sub_geometry in geometry.geoms:
            parts.extend(_polygon_parts(sub_geometry))
        return parts
    return []


def _safe_polygons(geometry) -> List["Polygon"]:  # noqa: F821
    """Returns the polygonal parts of ``geometry``, repairing invalid shapes.

    Repair is applied to each part individually. Calling ``make_valid`` on a
    whole MultiPolygon whose parts overlap (a common case for adjacent
    paddocks) would merge them into a single geometry and lose the paddock
    boundaries, so every part is validated on its own.
    """
    import shapely

    try:
        if geometry is None or geometry.is_empty:
            return []

        parts: List[Polygon] = []
        for part in _polygon_parts(geometry):
            if part.is_valid:
                parts.append(part)
                continue
            try:
                parts.extend(_polygon_parts(shapely.make_valid(part)))
            except Exception as error:  # pragma: no cover - defensive
                log_warning(f"geojson_io: invalid geometry skipped ({error})")
        return parts
    except Exception as error:  # pragma: no cover - defensive
        log_warning(f"geojson_io: invalid geometry skipped ({error})")
        return []


def _read_layers(path: Path, driver: str | None = None) -> List["gpd.GeoDataFrame"]:  # noqa: F821
    """Reads every vector layer of ``path`` (KML folders become layers)."""
    import geopandas as gpd

    dataframes: List[gpd.GeoDataFrame] = []
    try:
        layer_names = list(gpd.list_layers(path)["name"])
    except Exception:
        layer_names = [None]

    for layer_name in layer_names:
        try:
            kwargs = {"driver": driver} if driver else {}
            if layer_name is not None:
                kwargs["layer"] = layer_name
            gdf = gpd.read_file(path, **kwargs)
        except Exception as error:
            log_warning(f"geojson_io: failed reading layer {layer_name} of {path.name}: {error}")
            continue

        if gdf is None or gdf.empty:
            continue
        dataframes.append(gdf)

    if not dataframes:
        raise GeoFileError(
            f"Não foi possível ler nenhuma camada do arquivo {path.name}. "
            "Verifique se o arquivo está íntegro."
        )
    return dataframes


def _read_vector_file(path: Path) -> List["gpd.GeoDataFrame"]:  # noqa: F821
    """Reads a single vector file, choosing the driver by extension."""
    suffix = path.suffix.lower()

    if suffix == ".kmz":
        return _read_layers(path, driver="LIBKML")
    if suffix == ".kml":
        try:
            return _read_layers(path, driver="LIBKML")
        except GeoFileError:
            return _read_layers(path, driver="KML")
    return _read_layers(path)


def _extract_archive(content: bytes, filename: str, destination: Path) -> None:
    """Extracts a zip/rar archive into ``destination``."""
    suffix = Path(filename).suffix.lower()

    if suffix == ".zip":
        archive_path = destination / filename
        archive_path.write_bytes(content)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(destination)
        except zipfile.BadZipFile as error:
            raise GeoFileError(
                "O arquivo .zip enviado é inválido ou está corrompido."
            ) from error
        return

    try:
        import rarfile
    except ImportError as error:  # pragma: no cover - dependency check
        raise GeoFileError(
            "O suporte a arquivos .rar não está disponível no servidor no momento. "
            "Envie o arquivo como .zip ou .kmz."
        ) from error

    archive_path = destination / filename
    archive_path.write_bytes(content)
    try:
        with rarfile.RarFile(archive_path) as archive:
            archive.extractall(destination)
    except rarfile.RarCannotExec as error:
        raise GeoFileError(
            "Não foi possível extrair o arquivo .rar: o extrator não está instalado "
            "no servidor. Envie o arquivo como .zip ou .kmz."
        ) from error
    except Exception as error:
        raise GeoFileError(
            f"Não foi possível extrair o arquivo .rar. Verifique se ele está íntegro. "
            f"Detalhes: {error}"
        ) from error


def _collect_dataframes(content: bytes, filename: str, workdir: Path) -> List["gpd.GeoDataFrame"]:  # noqa: F821
    """Loads all vector dataframes contained in the uploaded file."""
    suffix = Path(filename).suffix.lower()

    if suffix in (".zip", ".rar"):
        archive_dir = workdir / "archive"
        archive_dir.mkdir()
        _extract_archive(content, filename, archive_dir)

        vector_files = sorted(
            p for p in archive_dir.rglob("*") if p.suffix.lower() in _ARCHIVE_VECTOR_EXTENSIONS
        )
        if not vector_files:
            raise GeoFileError(
                "O arquivo enviado não contém nenhum shapefile (.shp), KML ou GeoJSON. "
                "Envie um .zip/.rar com os arquivos do shapefile."
            )

        dataframes: List[gpd.GeoDataFrame] = []
        for vector_file in vector_files:
            try:
                dataframes.extend(_read_vector_file(vector_file))
            except GeoFileError:
                continue
        if not dataframes:
            raise GeoFileError(
                "Não foi possível ler os arquivos vetoriais contidos no arquivo enviado."
            )
        return dataframes

    file_path = workdir / filename
    file_path.write_bytes(content)
    return _read_vector_file(file_path)


def _normalize_layer(gdf: "gpd.GeoDataFrame") -> "gpd.GeoDataFrame":  # noqa: F821
    """Reprojects to WGS84 and drops Z.

    Geometry validity is handled per-part by ``_safe_polygons`` (calling
    ``make_valid`` here on a whole MultiPolygon with overlapping parts would
    merge adjacent paddocks).
    """
    import shapely

    if gdf.crs is None:
        log_warning("geojson_io: arquivo sem sistema de referência; assumindo EPSG:4326")
        gdf = gdf.set_crs(_WGS84_EPSG)
    elif gdf.crs.to_epsg() != _WGS84_EPSG:
        gdf = gdf.to_crs(_WGS84_EPSG)

    gdf = gdf[gdf.geometry.notna()].copy()
    gdf["geometry"] = gdf.geometry.apply(shapely.force_2d)
    return gdf


def _find_label_column(gdf: "gpd.GeoDataFrame") -> Optional[str]:  # noqa: F821
    """Returns the column holding the polygon names, or None when absent."""
    by_lower = {str(column).lower(): column for column in gdf.columns}
    for candidate in _LABEL_COLUMNS:
        if candidate in by_lower:
            return by_lower[candidate]
    return None


def _clean_label(value) -> Optional[str]:
    """Normalizes a source attribute value to a usable label (or None)."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text or text.lower() in ("nan", "none"):
        return None
    return text


def convert_geo_file_to_geojson(content: bytes, filename: str) -> bytes:
    """Converts any supported geospatial document to a single-geometry GeoJSON.

    All polygonal parts found across every feature/layer are merged into one
    geometry: a ``Polygon`` when there is a single part, otherwise a
    ``MultiPolygon``.

    Args:
        content: Raw bytes of the uploaded file.
        filename: Original filename (used to detect the format).

    Returns:
        GeoJSON ``FeatureCollection`` bytes in EPSG:4326.

    Raises:
        GeoFileError: When the file cannot be read or contains no polygon.
    """
    import geopandas  # noqa: F401
    import shapely
    from shapely.geometry import MultiPolygon, Polygon, mapping

    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFormatError(
            f"Formato não suportado ({suffix or 'desconhecido'}). "
            "Envie um arquivo .zip, .rar, .kmz, .kml ou .geojson."
        )

    with tempfile.TemporaryDirectory(prefix="geojson_io_") as tmp:
        dataframes = _collect_dataframes(content, filename, Path(tmp))

    polygons: List[Polygon] = []
    labels: List[Optional[str]] = []
    for gdf in dataframes:
        try:
            layer = _normalize_layer(gdf)
            label_column = _find_label_column(layer)
            for index, geometry in enumerate(layer.geometry):
                parts = _safe_polygons(geometry)
                label = _clean_label(layer[label_column].iloc[index]) if label_column else None
                polygons.extend(parts)
                labels.extend([label] * len(parts))
        except Exception as error:
            log_error(f"geojson_io: failed processing layer of {filename}: {error}")

    if not polygons:
        raise GeoFileError(
            "Nenhum polígono foi encontrado no arquivo enviado. "
            "São aceitos apenas arquivos com polígonos (limites da propriedade ou piquetes)."
        )

    geometry: Union[Polygon, MultiPolygon]
    if len(polygons) == 1:
        geometry = polygons[0]
    else:
        geometry = MultiPolygon(polygons)

    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "source_file": filename,
                    "polygon_count": len(polygons),
                    "polygon_labels": labels,
                },
                "geometry": mapping(geometry),
            }
        ],
    }

    return json.dumps(feature_collection, ensure_ascii=False).encode("utf-8")