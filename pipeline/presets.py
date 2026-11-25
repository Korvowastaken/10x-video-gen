"""Choices the script stage offers the model: looks and voices.

A look is a fixed style block (the PDF's "style block") added to every image
prompt, plus a short tag for every video prompt. Keeping it fixed in code, and
copied verbatim into storyboard.json, is what holds the look steady across shots.
"""
from __future__ import annotations

STYLES = {
    "low-poly-3d": {
        "block": ("Stylized low-poly 3D animation still: faceted surfaces with visible flat polygons, "
                  "toy-like rounded characters with simple dark oval eyes and small calm mouths, soft matte "
                  "materials, cinematic warm key light against cool deep-blue shadows, soft circular bokeh "
                  "lights in the background, shallow depth of field, gentle film grain"),
        "motion": "low-poly 3D animation, smooth and slow, faceted shapes stay stable, no morphing",
        "negative": ("photorealistic skin, realistic human photo, text, letters, subtitles, watermark, logo, "
                     "extra fingers, deformed hands, distorted face, blurry, low quality, flicker"),
        "palette": ["#0E1A33", "#F2A541", "#E86A33", "#F5E6C8", "#3B6E8F"],
    },
    "painted-2d": {
        "block": ("Warm hand-painted 2D storybook illustration: visible gouache brush strokes, soft paper "
                  "texture, simple expressive faces, golden-hour light, muted earthy palette with indigo shadows"),
        "motion": "hand-painted 2D animation, gentle parallax, slow and smooth",
        "negative": "photorealistic, 3D render, text, letters, watermark, extra fingers, distorted face, blurry",
        "palette": ["#2B2A4C", "#E9B44C", "#9B5523", "#F4E9D8", "#50808E"],
    },
    "claymation": {
        "block": ("Soft claymation stop-motion still: handmade plasticine characters with thumbprint texture, "
                  "miniature set, warm practical lights, shallow depth of field"),
        "motion": "stop-motion claymation, small deliberate movements",
        "negative": "photorealistic, text, letters, watermark, extra fingers, distorted face, blurry",
        "palette": ["#3D2C2E", "#E8A87C", "#C38D9E", "#F6EAD7", "#41B3A3"],
    },
}

# Gemini TTS prebuilt voices with Google's one-word descriptions. "f"/"m" is the
# rough pitch the voice reads as, to help cast an elder woman or a young man.
VOICES = {
    "Zephyr": ("f", "bright"), "Puck": ("m", "upbeat"), "Charon": ("m", "informative"),
    "Kore": ("f", "firm"), "Fenrir": ("m", "excitable"), "Leda": ("f", "youthful"),
    "Orus": ("m", "firm"), "Aoede": ("f", "breezy"), "Callirrhoe": ("f", "easy-going"),
    "Autonoe": ("f", "bright"), "Enceladus": ("m", "breathy"), "Iapetus": ("m", "clear"),
    "Umbriel": ("m", "easy-going"), "Algieba": ("m", "smooth"), "Despina": ("f", "smooth"),
    "Erinome": ("f", "clear"), "Algenib": ("m", "gravelly"), "Rasalgethi": ("m", "informative"),
    "Laomedeia": ("f", "upbeat"), "Achernar": ("f", "soft"), "Alnilam": ("m", "firm"),
    "Schedar": ("m", "even"), "Gacrux": ("f", "mature"), "Pulcherrima": ("f", "forward"),
    "Achird": ("m", "friendly"), "Zubenelgenubi": ("m", "casual"), "Vindemiatrix": ("f", "gentle"),
    "Sadachbia": ("m", "lively"), "Sadaltager": ("m", "knowledgeable"), "Sulafat": ("f", "warm"),
}

LANGUAGES = {
    "am": {"name": "Amharic", "script": "Ge'ez (Ethiopic)"},
    "om": {"name": "Afaan Oromo", "script": "Latin (Qubee)"},
    "ti": {"name": "Tigrinya", "script": "Ge'ez (Ethiopic)"},
    "so": {"name": "Somali", "script": "Latin"},
    "en": {"name": "English", "script": "Latin"},
}
