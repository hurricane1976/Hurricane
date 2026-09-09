"""Canonical fleet chart + identity palette — one source of truth.

Imported by build_metrics.py and build_observability.py (both run with cwd =
website/). Mirrored in /.well-known/design-tokens.json v2 as the fleet-shared
record. Before this module, build_metrics._AREA_COLORS, build_observability.
MM_COLOR and the React FleetGraph each assigned agent colours independently —
Highbeam was blue on one page and teal on another, and the observability
12-hue set failed CVD (Ridge↔Canyon ΔE 4.5).

TWO jobs, kept separate on purpose (per the dataviz method):

1. IDENTITY  — FAMILY / AGENT below. Colour encodes MODEL FAMILY
   (amber=Claude, teal=Gemini, blue=DeepSeek, magenta=GLM); the specific
   agent is always named by an adjacent text label (tab text, legend text,
   table row, node label). This is composite encoding — the sanctioned
   approach for >8 categories. Used for tab dots, legend swatches, per-agent
   table markers, and single-agent charts (the observability panel shows one
   agent at a time).

2. SERIES    — a small fixed categorical ramp for a genuine multi-series
   overlay (metrics multi_area_chart). Distinct from identity colour.

Validated with the dataviz skill's scripts/validate_palette.js on the dark
chart surface #10151d:
  FAMILY (4):  chroma PASS · normal-vision ΔE >=15.8 PASS · contrast PASS ·
               CVD teal<->magenta ΔE 6.3 (deutan) — the 6-8 "legal with
               secondary encoding" band; every use site carries a text label.
  SERIES (5):  chroma PASS · adjacent CVD ΔE 13.6 PASS · normal-vision 24 PASS
               · contrast PASS. If this chart ever needs a 6th series, facet
               it into small multiples instead of extending the ramp.
Lightness sits above the validator's dark band on purpose: the whole Beacon
UI is bright-accent-on-near-black and chart marks are tuned to match it,
consistently, across ~45 pages.
"""

# ---- model-family hues (identity) ------------------------------------------
FAMILY = {
    "Claude":   "#ff8a3d",
    "Gemini":   "#4fd1c5",
    "DeepSeek": "#5aa9ff",
    "GLM":      "#f06fb0",
}

AGENT_FAMILY = {
    "Beacon": "Claude", "Highbeam": "Claude", "Mountain": "Claude",
    "Tidal": "Gemini", "Lantern": "Gemini", "River": "Gemini",
    "Lightning": "DeepSeek", "Creek": "DeepSeek", "Stream": "DeepSeek",
    "Canyon": "DeepSeek",
    "Ridge": "GLM", "Harbor": "GLM",
}

# Per-agent shade for small identity marks where a family cluster needs a
# "which one" hint. Same hue as the family, stepped by lightness. Chart FILLS
# use FAMILY[...]; only dots / swatches / row markers use these.
AGENT = {
    "Beacon": "#ff8a3d", "Highbeam": "#ffab5e", "Mountain": "#d96a2a",
    "Tidal": "#4fd1c5", "Lantern": "#7ee0d6", "River": "#2f9e93",
    "Lightning": "#5aa9ff", "Creek": "#8cc3ff", "Stream": "#3f7fd6",
    "Canyon": "#6a86e6",
    "Ridge": "#f06fb0", "Harbor": "#f59ccb",
}

# ---- multi-series overlay ramp (series, not identity) --------------------
# Order is fixed and assigned by position, never cycled.
SERIES = ["#ff8a3d", "#4fd1c5", "#b98cff", "#f4c752", "#3fa9f5"]

# Fleet render order (on-box four first), shared by any surface that lists
# every agent so the order never drifts between pages.
FLEET_ORDER = [
    "Beacon", "Highbeam", "Lantern", "Lightning",
    "Tidal", "River", "Creek", "Stream",
    "Mountain", "Canyon", "Ridge", "Harbor",
]


def family_of(agent: str) -> str:
    return AGENT_FAMILY.get(agent, "Claude")


def family_color(agent: str) -> str:
    """The model-family hue — use for chart fills / strokes."""
    return FAMILY[family_of(agent)]


def agent_color(agent: str) -> str:
    """The agent's own shade — use for dots, swatches, single-agent marks."""
    return AGENT.get(agent, family_color(agent))
