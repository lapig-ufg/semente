"""Tests of the onboarding tutorial video (``features.onboarding-video``).

Covers ``Harness._attach_onboarding_video``: the video goes once per user,
a disabled feature or a missing file never breaks the reply, and media
already in the reply is kept.
"""

from semente.core.harness import Harness
from semente.core.types import StepOutput
from semente.manifest import Manifest


def _harness(tmp_path, cfg=None) -> Harness:
    features = {"onboarding-video": cfg} if cfg is not None else {}
    return Harness(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app", features=features, source_dir=tmp_path),
    )


def _video_cfg(tmp_path) -> dict:
    (tmp_path / "tutorial.mp4").write_bytes(b"fake-mp4")
    return {"file": "tutorial.mp4"}


def test_attaches_video_only_once(tmp_path):
    harness = _harness(tmp_path, _video_cfg(tmp_path))
    state: dict = {}

    first = harness._attach_onboarding_video(StepOutput(content="Pronto!"), state)
    assert len(first.videos) == 1
    assert first.videos[0].content == b"fake-mp4"
    assert state["onboarding_video_sent"] is True

    second = harness._attach_onboarding_video(StepOutput(content="Oi"), state)
    assert second.videos is None


def test_feature_off_sends_nothing(tmp_path):
    state: dict = {}
    out = _harness(tmp_path)._attach_onboarding_video(StepOutput(content="Pronto!"), state)
    assert out.videos is None
    assert "onboarding_video_sent" not in state


def test_missing_file_does_not_break(tmp_path):
    state: dict = {}
    harness = _harness(tmp_path, {"file": "nao_existe.mp4"})
    out = harness._attach_onboarding_video(StepOutput(content="Pronto!"), state)
    assert out.content == "Pronto!"
    assert out.videos is None
    assert "onboarding_video_sent" not in state


def test_keeps_videos_already_in_reply(tmp_path):
    harness = _harness(tmp_path, _video_cfg(tmp_path))
    out = harness._attach_onboarding_video(
        StepOutput(content="Pronto!", videos=["outro-video"]), {}
    )
    assert len(out.videos) == 2
    assert out.videos[0] == "outro-video"


def test_absolute_path(tmp_path):
    _video_cfg(tmp_path)
    absolute = str(tmp_path / "tutorial.mp4")
    out = _harness(tmp_path, {"file": absolute})._attach_onboarding_video(
        StepOutput(content="Pronto!"), {}
    )
    assert len(out.videos) == 1
