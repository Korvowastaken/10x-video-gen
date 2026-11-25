"""The final cut spends RIFE only where it shows, and renders only the part of a masked loop it uses."""
import numpy as np
import pytest

from pipeline import assemble, motion


def _video(path, frames: int, fps: float, size=(64, 112)):
    w, h = size
    shades = (np.arange(frames) * 255 // max(1, frames - 1)).astype(np.uint8)
    motion.write_frames((np.full((h, w, 3), s, np.uint8) for s in shades), path, fps)
    return path


def test_rife_only_when_slowing_down_or_raising_the_frame_rate():
    assert not motion.needs_rife(30, 24, 1.0)  # 30 fps clip into a 24 fps film: drop frames
    assert motion.needs_rife(30, 24, 1.25)  # slowed down: needs new frames
    assert motion.needs_rife(16, 24, 1.0)  # a 16 fps clip: needs new frames to reach 24


@pytest.fixture
def no_rife(monkeypatch):
    def refuse(*_):
        raise AssertionError("RIFE started where it was not needed")
    monkeypatch.setattr(assemble, "_interpolator", refuse)


def test_a_long_masked_loop_renders_only_what_the_shot_shows(tmp_path, no_rife, capsys):
    loop = _video(tmp_path / "loop.mp4", 320, 30)  # a 10.7 s cycle, like a composited masked scene
    out = tmp_path / "seg.mp4"
    assemble.render_segment({"kind": "loop", "path": loop}, 2.0, out, w=64, h=112, fps=24)
    assert motion.probe_video(out)["fps"] == 24
    assert len(motion.read_frames(out)[0]) == 48
    assert "62 frames" in capsys.readouterr().out  # 2 s of the 30 fps cycle, not all 320 frames


def test_a_loop_shorter_than_the_shot_still_fills_it(tmp_path, no_rife):
    loop = _video(tmp_path / "loop.mp4", 30, 30)  # a 1 s cycle in a 2.5 s shot
    out = tmp_path / "seg.mp4"
    assemble.render_segment({"kind": "loop", "path": loop}, 2.5, out, w=64, h=112, fps=24)
    assert len(motion.read_frames(out)[0]) == 60


def test_a_clip_at_normal_speed_drops_frames_instead_of_running_rife(tmp_path, no_rife):
    clip = _video(tmp_path / "clip.mp4", 161, 30)  # 5.37 s, as WaveSpeed returns them
    out = tmp_path / "seg.mp4"
    assemble.render_segment({"kind": "clip", "path": clip, "cap": 1.25}, 5.0, out, w=64, h=112, fps=24)
    assert len(motion.read_frames(out)[0]) == 120


class _BlackRife:
    """Stands in for RIFE on an Intel UHD 620: it runs, and every frame it returns is black."""

    def __init__(self, **_):
        pass

    def process_cv2(self, a, b, timestep=0.5):
        return np.zeros_like(a)


@pytest.fixture
def black_rife(monkeypatch):
    import sys
    import types
    monkeypatch.setitem(sys.modules, "rife_ncnn_vulkan_python", types.SimpleNamespace(Rife=_BlackRife))
    monkeypatch.setattr(motion, "rife_model_dir", lambda *_: "unused")
    monkeypatch.setattr(assemble, "_INTERPOLATORS", {})
    monkeypatch.setattr(motion, "_ENGINE", None, raising=False)


def test_a_gpu_whose_rife_returns_black_frames_never_reaches_the_film(tmp_path, black_rife, capsys):
    clip = _video(tmp_path / "clip.mp4", 161, 30)
    out = tmp_path / "seg.mp4"
    # 5.25 s of clip in a 5.5 s shot: slowed, so in-between frames are needed
    assemble.render_segment({"kind": "clip", "path": clip, "cap": 1.25}, 5.5, out, w=64, h=112, fps=24)
    frames = motion.read_frames(out)[0]
    assert len(frames) == 132
    darkest = min(float(f.mean()) for f in frames[8:])  # the test clip fades up from black over its first frames
    assert darkest > 10, f"a black frame reached the segment (brightness {darkest:.1f})"
    assert "black" in capsys.readouterr().out  # and the log says why it did not use RIFE
