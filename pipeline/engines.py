"""Motion modes and the engines behind them, chosen per shot.

storyboard.json sets shots[].motion.mode (what kind of movement) and, if it
wants, motion.engine (which model makes the paid clip). The defaults follow the
"balanced" plan in research/motion-on-a-budget.md: paid image-to-video only
where a person acts or a detail must move, free local motion everywhere else.

Adding an engine is one entry here plus a function in its provider module.
"""
from __future__ import annotations

VIDEO_ENGINES = {
    "wavespeed-wan22-480p": {"provider": "wavespeed", "model": "wavespeed-ai/wan-2.2/i2v-480p-ultra-fast",
                             "clip_s": (5, 8), "usd": {5: 0.05, 8: 0.08}, "last_image": True},
    "wavespeed-wan22-720p": {"provider": "wavespeed", "model": "wavespeed-ai/wan-2.2/i2v-720p-ultra-fast",
                             "clip_s": (5, 8), "usd": {5: 0.10, 8: 0.16}, "last_image": True},
    # Kept as a fallback provider; its Kaggle job has not been run end to end (FAILURES.md F12).
    "kaggle-wan22-ti2v-5b": {"provider": "kaggle", "model": "Wan-AI/Wan2.2-TI2V-5B-Diffusers",
                             "clip_s": (5,), "usd": {}, "last_image": False},
}

MUSIC_ENGINES = {
    "wavespeed-ace-step-1.5": {"provider": "wavespeed", "model": "wavespeed-ai/ace-step-1.5", "usd_per_s": 0.0003},
    "kaggle-ace-step-1.5": {"provider": "kaggle", "model": "ACE-Step/Ace-Step1.5"},
}

# paid: needs a generated clip. subject: decides the slow-motion cap (research 3c).
MODES = {
    "full_i2v": {"paid": True, "subject": "character",
                 "about": "the whole keyframe animated by image-to-video"},
    "flf_inbetween": {"paid": True, "subject": "character",
                      "about": "a move from this keyframe to motion.end_keyframe (the model's last_image)"},
    "masked_i2v": {"paid": True, "subject": "character",
                   "about": "one clip composited onto the still inside motion.mask; the rest stays still"},
    "cinemagraph": {"paid": True, "subject": "ambient",
                    "about": "a masked clip whose region ping-pongs to fill any length"},
    "parallax": {"paid": False, "subject": "ambient",
                 "about": "a 2.5D camera move from a depth map (Depth Anything V2 Small, local)"},
    "still_kenburns": {"paid": False, "subject": "ambient", "about": "a slow pan or zoom over the still"},
    "still": {"paid": False, "subject": "ambient", "about": "the still, held"},
}

STRETCH_CAP = {"character": 1.25, "ambient": 1.6}

# When a mode cannot be produced (no clip after 3 attempts, budget or credit gone),
# assembly walks this chain and records which one it used.
FALLBACK = {
    "full_i2v": ["parallax", "still_kenburns"],
    "flf_inbetween": ["parallax", "still_kenburns"],
    "masked_i2v": ["parallax", "still_kenburns"],
    "cinemagraph": ["parallax", "still_kenburns"],
    "parallax": ["still_kenburns"],
    "still_kenburns": [],
    "still": [],
}

LEGACY_MODES = {"video": "full_i2v", "kenburns": "still_kenburns"}


def video_engine(name: str) -> dict:
    if name not in VIDEO_ENGINES:
        raise KeyError(f"unknown video engine '{name}' (known: {', '.join(VIDEO_ENGINES)})")
    return VIDEO_ENGINES[name]


def music_engine(name: str) -> dict:
    if name not in MUSIC_ENGINES:
        raise KeyError(f"unknown music engine '{name}' (known: {', '.join(MUSIC_ENGINES)})")
    return MUSIC_ENGINES[name]


def stretch_cap(shot: dict) -> float:
    motion = shot["motion"]
    subject = motion.get("subject") or MODES[motion["mode"]]["subject"]
    return STRETCH_CAP[subject]
