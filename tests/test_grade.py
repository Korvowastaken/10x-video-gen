"""The colour grade moves scenes toward one look, writes a LUT FFmpeg accepts, and edit.use picks the mode."""
import cv2
import numpy as np

from pipeline import assemble, grade
from pipeline.media import run_ffmpeg


def _image(seed: int, tint=(0, 0, 0)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = cv2.resize(rng.integers(30, 220, (12, 9, 3), dtype=np.uint8), (90, 120), interpolation=cv2.INTER_CUBIC)
    return np.clip(base.astype(int) + tint, 0, 255).astype(np.uint8)


def test_lut_is_identity_when_stats_match_target():
    s = grade.stats(_image(1))
    table = grade.lut(s, s)
    axis = np.linspace(0, 1, grade.SIZE)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    assert np.abs(table - np.stack([r, g, b], -1)).max() < 0.01


def test_grading_moves_an_image_toward_the_target():
    look_image, odd = _image(2), _image(3, tint=(50, 10, -40))
    look = grade.stats(look_image)
    graded = grade.apply(odd, grade.lut(grade.stats(odd), look, 0.6))
    gap = lambda im: np.abs(np.array(grade.stats(im)["mean"]) - look["mean"]).sum()  # noqa: E731
    assert gap(graded) < 0.6 * gap(odd)
    assert grade.distance(graded, look_image) < grade.distance(odd, look_image)


def test_write_cube_rows_and_ffmpeg_accepts_it(tmp_path):
    s = grade.stats(_image(4))
    cube = grade.write_cube(tmp_path / "g.cube", grade.lut(s, {"mean": [50, 5, 5], "std": s["std"]}))
    rows = [r for r in cube.read_text().splitlines() if r and r[0].isdigit()]
    assert len(rows) == 33 ** 3
    cv2.imwrite(str(tmp_path / "in.png"), _image(4))
    run_ffmpeg(["-i", str(tmp_path / "in.png"), "-vf", "lut3d=g.cube", str(tmp_path / "out.png")], cwd=tmp_path)
    assert (tmp_path / "out.png").stat().st_size > 0


def test_distance_to_self_is_zero():
    im = _image(5)
    assert grade.distance(im, im) == 0
    assert grade.neighbour_distances([im, im, _image(6)])[0] == 0


def test_edit_use_changes_the_starting_mode(monkeypatch, tmp_path):
    keyframe = tmp_path / "S03.jpg"
    keyframe.write_bytes(b"x")
    monkeypatch.setattr(assemble.StageCache, "current", lambda self, item: keyframe)
    tried = []
    monkeypatch.setattr(assemble, "_source_for",
                        lambda project, sb, shot, mode, kf: tried.append(mode) or {"kind": "image", "path": kf})
    shot = {"id": "S03", "motion": {"mode": "flf_inbetween"}}
    sb = {"edit": {"use": {"S03": "parallax"}}, "shots": [shot]}
    project = type("P", (), {"outputs": tmp_path})()
    source = assemble.shot_source(project, sb, shot, "final")
    assert tried == ["parallax"] and source["used"] == "parallax" and source["wanted"] == "parallax"
    tried.clear()
    assert assemble.shot_source(project, {"shots": [shot]}, shot, "final")["used"] == "flf_inbetween"
