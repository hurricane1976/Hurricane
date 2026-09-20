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
                            # fleet's direct-escalation gate, RETIRED again
                            # 2026-09-19 (Radar moved to GLM too), then
                            # REACTIVATED 2026-09-20 when Beacon itself moved
                            # back to Claude Code / Sonnet (josh-directed);
                            # Pulsar (this box) moved to Claude Code / Sonnet
                            # the same morning (josh-directed, ~09:37Z).
    "DeepSeek": "#5aa9ff",
    "GLM":      "#f06fb0",
    "Gemini":   "#4fd1c5",  # RETIRED 2026-09-09 — no live agent; kept so
                            # historical Gemini rows in observability.jsonl
                            # still resolve a colour.
    "Muse":     "#6fcf97",  # 2026-09-19: Muse Spark 1.2 joined the fleet
                            # (Brook on Tidal's host, Mesa on Mountain's box).
                            # RETIRED 2026-09-20: both moved to gpt-5.6-luna
                            # (Tidal's own page; Mountain's manifest + fleet.json)
                            # -- no live Muse node; kept so historical rows
                            # still resolve a colour.
    "GPT":      "#ff6b6b",  # 2026-09-20: gpt-5.6-luna via Codex CLI -- Prism
                            # (per its own AGENT.md/wake.sh + 10:16Z run), then
                            # Brook + Mist (Tidal's own page: operator directive
                            # 2026-09-20) and Mesa + Vista (Mountain's manifest
                            # + fleet.json, first-party). Coral sits apart from
                            # the amber Claude hue by hue + label.
    "Qwen":     "#e8c766",  # 2026-09-19 (late): Qwen joined (Pulsar, Vista,
                            # Mist). RETIRED 2026-09-20: Pulsar -> Claude, Mist
                            # and Vista -> gpt-5.6-luna -- no live Qwen node;
                            # kept so historical rows still resolve a colour.
                            # Gold sat apart from the magenta/green/blue cluster.
                            # Identity stays composite (family hue + adjacent
                            # text label everywhere), which covers the CVD
                            # proximity between gold and Muse-green.
}

AGENT_FAMILY = {
    # Beacon: GLM 2026-09-15 -> 2026-09-20, then back to Claude Code / Sonnet
    # (josh-directed switch back) -- see fleet_palette.py FAMILY comment.
    "Beacon": "Claude", "Mountain": "Claude",   # Mountain: own manifest 2026-09-20 "engine switch back"
    "Lightning": "GLM", "Creek": "GLM", "Stream": "GLM",
    "Canyon": "GLM",
    "Highbeam": "GLM", "Lantern": "GLM",
    "Tidal": "Claude",   # Tidal's own manifest/fleet.json: claude -p --model sonnet, operator directive 2026-09-20
    "River": "GLM", "Ridge": "GLM", "Harbor": "GLM",
    # Radar: Claude until 2026-09-19, then GLM (josh-directed switch) -- the
    # fleet's last non-GLM node until Brook + Mesa joined the same day.
    "Radar": "GLM",
    "Meadow": "GLM", "Delta": "GLM",
    "Prism": "GPT",
    # 2026-09-20: Brook + Mist (Tidal's own page: gpt-5.6-luna via Codex, operator
    # directive) and Mesa + Vista (Mountain's manifest + fleet.json, first-party:
    # gpt-5.6-luna via Codex) all left Muse Spark / Qwen for GPT. Tidal's page still
    # lists Mesa/Vista under their old families -- second-hand from Mountain's feed;
    # the host that runs them is authoritative.
    "Brook": "GPT", "Mist": "GPT", "Mesa": "GPT", "Vista": "GPT",
    # Pulsar ran Qwen 3.8 27B Free 2026-09-19 -> 2026-09-20, then moved to
    # Claude Code / Sonnet (josh-directed, ~09:37Z; first Claude run 09:39Z).
    "Pulsar": "Claude",
}

# Per-agent shade for small identity marks where a family cluster needs a
# "which one" hint. Same hue as the family, stepped by lightness. Chart FILLS
# use FAMILY[...]; only dots / swatches / row markers use these.
AGENT = {
    # Claude (amber), stepped by lightness — Beacon takes the family hue; Pulsar,
    # Tidal and Mountain (all Claude Code from 2026-09-20) take the other steps.
    "Beacon": "#ff8a3d", "Pulsar": "#ffb27a",
    "Tidal": "#d9722a", "Mountain": "#ffc9a0",
    # GLM (magenta), stepped by lightness — the whole fleet shares the hue.
    # Lightning/Creek/Stream/Canyon were re-hued 2026-09-20: they carried
    # leftover DeepSeek-blue shades (#5aa9ff/#8cc3ff/#3f7fd6/#6a86e6) from
    # before their family moved to GLM — orphaned when the DeepSeek block
    # comment above them was removed but the values themselves never
    # migrated, contradicting this dict's own "same hue as the family" rule.
    "Highbeam": "#b8447d",
    "River": "#c94f8c", "Ridge": "#f06fb0",
    "Harbor": "#f59ccb", "Lantern": "#fbc0e0",
    "Lightning": "#d968a2", "Creek": "#a4376f", "Stream": "#732b50",
    "Canyon": "#fcdeed",
    # Radar moved to the GLM family 2026-09-19; its amber identity shade is
    # retired with the family (historical amber rows resolve via the family
    # colour, not this per-agent shade).
    "Radar": "#e87fb4",
    "Meadow": "#d25596", "Delta": "#8f2f60",
    # GPT (coral), stepped by lightness — Prism takes the family hue; Brook, Mist,
    # Mesa and Vista (gpt-5.6-luna via Codex from 2026-09-20) take the other steps.
    "Prism": "#ff6b6b", "Brook": "#ff9494", "Mist": "#d94f4f",
    "Mesa": "#ffb8b8", "Vista": "#b83c3c",
}

# ---- multi-series overlay ramp (series, not identity) --------------------
# Order is fixed and assigned by position, never cycled.
SERIES = ["#ff8a3d", "#4fd1c5", "#b98cff", "#f4c752", "#3fa9f5"]

# Fleet render order (on-box agents first), shared by any surface that lists
# every agent so the order never drifts between pages.
FLEET_ORDER = [
    "Beacon", "Highbeam", "Lantern", "Lightning", "Radar", "Prism", "Pulsar",
    "Tidal", "River", "Creek", "Stream", "Meadow", "Brook", "Mist",
    "Mountain", "Canyon", "Ridge", "Harbor", "Delta", "Mesa", "Vista",
]


def family_of(agent: str) -> str:
    return AGENT_FAMILY.get(agent, "GLM")


def family_color(agent: str) -> str:
    """The model-family hue — use for chart fills / strokes."""
    return FAMILY[family_of(agent)]


def agent_color(agent: str) -> str:
    """The agent's own shade — use for dots, swatches, single-agent marks."""
    return AGENT.get(agent, family_color(agent))
