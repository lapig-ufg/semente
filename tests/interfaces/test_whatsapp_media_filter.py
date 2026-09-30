"""Tests for the WhatsApp router's generated-media filter.

Some engines return in the run output the same media instances passed to
``run()`` (shallow-copied lists), so the router must filter them to avoid
echoing the user's media back. ``filter_generated_media`` also drops
internal GeoJSON artifacts (``format="geojson"``).

    .venv/bin/python -m pytest tests/interfaces/test_whatsapp_media_filter.py -v
"""

from semente.core.types import StepOutput
from semente.interfaces.whatsapp.helpers import filter_generated_media
from semente.tools.types import Audio, File, Image, Video


class TestInputMediaEcho:
    def test_same_instance_is_filtered_out(self):
        img = Image(content=b"img", mime_type="image/jpeg")
        aud = Audio(content=b"aud", mime_type="audio/ogg")
        vid = Video(content=b"vid", mime_type="video/mp4")
        doc = File(content=b"doc", mime_type="application/pdf", name="doc.pdf")

        response = StepOutput(images=[img], videos=[vid], audio=[aud], files=[doc])
        input_media = {
            "images": [img],
            "videos": [vid],
            "audio": [aud],
            "files": [doc],
        }

        assert filter_generated_media(response, input_media) == {}

    def test_input_media_alone_produces_empty_result(self):
        img = Image(content=b"img", mime_type="image/jpeg")
        response = StepOutput(images=[img])

        assert filter_generated_media(response, {"images": [img]}) == {}


class TestGeneratedMediaKept:
    def test_new_instances_are_kept(self):
        input_img = Image(content=b"input", mime_type="image/jpeg")
        generated_img = Image(content=b"generated", mime_type="image/png")
        generated_audio = Audio(content=b"tts", mime_type="audio/mpeg")

        response = StepOutput(images=[input_img, generated_img], audio=[generated_audio])
        result = filter_generated_media(response, {"images": [input_img], "audio": []})

        assert result == {
            "images": [generated_img],
            "audio": [generated_audio],
        }

    def test_mixed_input_and_generated_in_same_list(self):
        input_file = File(content=b"input", mime_type="application/pdf")
        generated_file = File(content=b"report", mime_type="application/pdf")

        response = StepOutput(files=[input_file, generated_file])
        result = filter_generated_media(response, {"files": [input_file]})

        assert result == {"files": [generated_file]}


class TestGeojsonArtifacts:
    def test_geojson_file_dropped_even_if_not_in_input(self):
        geo_file = File(
            content=b"{}",
            mime_type="application/json",
            name="property.json",
            format="geojson",
        )

        response = StepOutput(files=[geo_file])
        result = filter_generated_media(response, {})

        assert result == {}

    def test_non_geojson_files_kept(self):
        regular = File(content=b"x", mime_type="application/pdf", name="x.pdf")

        response = StepOutput(files=[regular])
        result = filter_generated_media(response, {})

        assert result == {"files": [regular]}


class TestEdgeCases:
    def test_empty_response_attrs_and_missing_input_keys(self):
        response = StepOutput()
        result = filter_generated_media(response, {})

        assert result == {}

    def test_none_response_attrs(self):
        response = StepOutput()
        result = filter_generated_media(response, {"images": None})

        assert result == {}

    def test_response_without_media_attributes(self):
        class Bare:
            pass

        result = filter_generated_media(Bare(), {"images": [Image(content=b"i")]})

        assert result == {}