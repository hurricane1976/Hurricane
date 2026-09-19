"""Canonical fleet chart + identity palette — one source of truth.

Imported by build_metrics.py and build_observability.py (both run with cwd =
website/). Mirrored in /.well-known/design-tokens.json v2 as the fleet-shared
record. Before this module, build_metrics._AREA_COLORS, build_observability.
MM_COLOR and the React FleetGraph each assigned agent colours independently —
Highbeam was blue on one page and teal on another, and the observability
12-hue set failed CVD (Ridge↔Canyon ΔE 4.5).

TWO jobs, kept separate on purpose (per the dataviz method):

1. IDENTITY  — FAMILY / AGENT below. Colour encodes MODEL FAMILY
   (amber=Claude, blue=DeepSeek, magenta=GLM); the specific
   agent is always named by an adjacent text label (tab text, legend text,
   table row, node label). This is composite encoding — the sanctioned
   approach for >8 categories. Used for tab dots, legend swatches, per-agent
   table markers, and single-agent charts (the observability panel shows one
   agent at a time).

2. SERIES    — a small fixed categorical ramp for a genuine multi-series
   overlay (metrics multi_area_chart). Distinct from identity colour.

Validated with the dataviz skill's scripts/validate_palette.js on the dark
chart surface #10151d:
  FAMILY (3):  chroma PASS · normal-vision ΔE >=15.8 PASS · contrast PASS ·
               CVD PASS (Gemini/teal retired from the fleet 2026-09-09 when
               Lantern/Tidal/River moved to GLM Flash; the teal hue is kept
               below only so historical Gemini rows still resolve a colour).
  SERIES (5):  chroma PASS · adjacent CVD ΔE 13.6 PASS · normal-vision 24 PASS
               · contrast PASS. If this chart ever needs a 6th series, facet
               it into small multiples instead of extending the ramp.
Lightness sits above the validator's dark band on purpose: the whole Beacon
UI is bright-accent-on-near-black and chart marks are tuned to match it,
consistently, across ~45 pages.
"""

# ---- model-family hues (identity) ------------------------------------------
FAMILY = {
    "Claude":   "#ff8a3d",  # RETIRED 2026-09-15 when the last three Claude Code
                            # agents (Beacon, Highbeam, Mountain) moved to GLM
                            # Flash Latest on opencode — REACTIVATED 2026-09-16
                            # when Radar (Claude Code, Sonnet) joined as the
                            # fleet's direct-escalation gate, then RETIRED for
                            # good 2026-09-19: Radar moved to GLM too (josh's
                            # switch), so no live agent runs Claude any more.
                            # Kept so historical rows still resolve a colour.
    "DeepSeek": "#5aa9ff",
    "GLM":      "#f06fb0",
    "Gemini":   "#4fd1c5",  # RETIRED 2026-09-09 — no live agent; kept so
                            # historical Gemini rows in observability.jsonl
                            # still resolve a colour.
    "Muse":     "#6fcf97",  # 2026-09-19: Muse Spark 1.2 joined the fleet
                            # (Brook on Tidal's host, Mesa on Mountain's box;
                            # both per the manifests). Green sits well apart
                            # from the GLM magenta cluster on the dark surface.
}

AGENT_FAMILY = {
    "Beacon": "GLM", "Mountain": "GLM",
    "Lightning": "GLM", "Creek": "GLM", "Stream": "GLM",
    "Canyon": "GLM",
    "Highbeam": "GLM", "Lantern": "GLM", "Tidal": "GLM",
    "River": "GLM", "Ridge": "GLM", "Harbor": "GLM",
    # Radar: Claude until 2026-09-19, then GLM (josh-directed switch) -- the
    # fleet's last non-GLM node until Brook + Mesa joined the same day.
    "Radar": "GLM",
    "Meadow": "GLM", "Delta": "GLM",
    "Prism": "GLM",
    "Brook": "Muse", "Mesa": "Muse",
}

# Per-agent shade for small identity marks where a family cluster needs a
# "which one" hint. Same hue as the family, stepped by lightness. Chart FILLS
# use FAMILY[...]; only dots / swatches / row markers use these.
AGENT = {
    "Beacon": "#a83a70", "Mountain": "#c94f8c",
    "Lightning": "#5aa9ff", "Creek": "#8cc3ff", "Stream": "#3f7fd6",
    "Canyon": "#6a86e6",
    # GLM (magenta), stepped by lightness — the whole fleet shares the hue.
    "Highbeam": "#b8447d",
    "River": "#c94f8c", "Tidal": "#e05fa0", "Ridge": "#f06fb0",
    "Harbor": "#f59ccb", "Lantern": "#fbc0e0",
    # Radar moved to the GLM family 2026-09-19; its amber identity shade is
    # retired with the family (historical amber rows resolve via the family
    # colour, not this per-agent shade).
    "Radar": "#e87fb4",
    "Meadow": "#d25596", "Delta": "#8f2f60", "Prism": "#f8a9cf",
    # Muse Spark (green), stepped by lightness — Brook (darker) and Mesa
    # (the family hue) joined 2026-09-19.
    "Brook": "#3f9d6a", "Mesa": "#6fcf97",
}

# ---- multi-series overlay ramp (series, not identity) --------------------
# Order is fixed and assigned by position, never cycled.
SERIES = ["#ff8a3d", "#4fd1c5", "#b98cff", "#f4c752", "#3fa9f5"]

# Fleet render order (on-box agents first), shared by any surface that lists
# every agent so the order never drifts between pages.
FLEET_ORDER = [
    "Beacon", "Highbeam", "Lantern", "Lightning", "Radar", "Prism",
    "Tidal", "River", "Creek", "Stream", "Meadow", "Brook",
    "Mountain", "Canyon", "Ridge", "Harbor", "Delta", "Mesa",
]


def family_of(agent: str) -> str:
    return AGENT_FAMILY.get(agent, "GLM")


def family_color(agent: str) -> str:
    """The model-family hue — use for chart fills / strokes."""
    return FAMILY[family_of(agent)]


def agent_color(agent: str) -> str:
    """The agent's own shade — use for dots, swatches, single-agent marks."""
    return AGENT.get(agent, family_color(agent))
