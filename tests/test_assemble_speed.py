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
