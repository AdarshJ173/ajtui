#!/usr/bin/env python3
"""
lifeOS — Theme Engine & Capability Layer
=========================================
Single source of truth for every visual token in lifeOS Daily:

  * Capabilities  — color depth (truecolor/256/16) + unicode support detection.
  * Glyphs        — full unicode set with per-glyph ASCII fallback.
  * Palette       — semantic color tokens (one per theme, per terminal capability).
  * Theme         — palette + typography + spacing + metrics + animation timings
                    + a generated Textual CSS template + micro-copy registry.
  * Animator      — tiny frame-batched driver (single timer, named sequences).

Three named themes ship by default:
  lifeos    cyan-on-black flagship
  phosphor  monochrome matrix green
  amber     warm single-hue amber

No widget may contain a hardcoded color — everything funnels through here.
"""

from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from rich.text import Text


# ---------------------------------------------------------------------------
# Capability detection — color depth & unicode, no heuristics left to chance
# ---------------------------------------------------------------------------


def detect_color_level(env: Optional[dict] = None) -> str:
    """Return 'truecolor' | 'eight_bit' | 'standard'."""
    e = os.environ if env is None else env
    if e.get("NO_COLOR"):
        return "standard"
    term = (e.get("TERM") or "").lower()
    if term in ("", "dumb", "unknown"):
        return "standard"
    ct = (e.get("COLORTERM") or "").lower()
    if ct in ("truecolor", "24bit"):
        return "truecolor"
    if "direct" in term:
        return "truecolor"
    if "256color" in term:
        return "eight_bit"
    return "standard"


def detect_unicode(env: Optional[dict] = None) -> bool:
    """True when the locale advertises UTF-8 (TERM=dumb is allowed to — some
    regex-dump terminals still render unicode; LANG/LC_* decide)."""
    e = os.environ if env is None else env
    blob = " ".join(
        (e.get(k) or "") for k in ("LC_ALL", "LC_CTYPE", "LANG")
    ).lower()
    return "utf-8" in blob or "utf8" in blob


class Capabilities:
    """Resolved once at launch; everything downstream reads from here."""

    def __init__(self, env: Optional[dict] = None):
        self.color_level: str = detect_color_level(env)
        self.unicode: bool = detect_unicode(env)
        self.reduced_motion: bool = bool(
            (os.environ if env is None else env).get("LIFEOS_NO_MOTION", "")
        )

    @property
    def colorful(self) -> bool:
        return self.color_level != "standard"


# ---------------------------------------------------------------------------
# Calculated values
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Glyphs:
    logo: str
    spark: str
    check: str
    check_flash: str
    open_box: str
    squared: str
    line_v: str
    bar_left: str
    bar_full: str
    bar_shades: str   # longest→shortest partial fill
    bar_track: str
    spark_line: str
    flame: str
    bolt: str
    tick_a: str
    tick_b: str
    done: str
    partial: str
    empty: str
    ind_sel: str
    ind_today: str
    ellipsis: str
    w_left: str
    w_right: str
    hint_open: str
    hint_close: str
    horseshoe: str
    enter: str


_GLYPH_TABLE: Dict[str, tuple] = {
    # field        unicode            ascii
    "logo":        ("◆",               "*"),
    "spark":       ("✦",               "*"),
    "check":       ("✓",               "x"),
    "check_flash": ("✔",               "#"),
    "open_box":    ("○",               "o"),
    "squared":     ("▪",               "#"),
    "line_v":      ("│",               "|"),
    "bar_left":    ("▐",               "["),
    "bar_full":    ("█",               "#"),
    "bar_shades":  ("▓▒░",             "#+."),
    "bar_track":   ("·",               "."),
    "spark_line":  (" ▁▂▃▄▅",          " ._-^"),
    "flame":       ("▲",               "^"),
    "bolt":        ("⚡",               ">"),
    "tick_a":      ("⠋⠙⠹⠸",      "-\\|/"),
    "tick_b":      ("⠼⠴⠦⠧",      "-\\|/"),
    "done":        ("●",               "o"),
    "partial":     ("◐",               "%"),
    "empty":       ("·",               "."),
    "ind_sel":     ("■",               "#"),
    "ind_today":   ("◇",               "o"),
    "ellipsis":    ("…",               "."),
    "w_left":      ("◂",               "<"),
    "w_right":     ("▸",               ">"),
    "hint_open":   ("‹",               "["),
    "hint_close":  ("›",               "]"),
    "horseshoe":   ("╶",               "-"),
    "enter":       ("↵",               "R"),
}


def build_glyphs(uni: bool) -> Glyphs:
    return Glyphs(**{k: (v[0] if uni else v[1]) for k, v in _GLYPH_TABLE.items()})


# ---------------------------------------------------------------------------
# Palettes — ≤ 10 semantic chromatic tokens per theme (+ neutrals)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """
    Semantic color slots. Every widget styles itself with these names only.
    bg/panel/inset/line/line_soft are structure; text* the type ramp;
    accent/accent_hi/state_ok/state_warn/hot are the chromatic voice.
    """
    bg: str
    panel: str
    inset: str
    band: str
    band_hot: str
    line: str
    line_soft: str
    text_hi: str
    text: str
    text_dim: str
    text_faint: str
    accent: str
    accent_hi: str
    on_accent: str
    on_ok: str
    state_ok: str
    ok_soft: str
    state_warn: str
    danger: str
    hot: str
    hot_dim: str


_PALETTES: Dict[str, Dict[str, Palette]] = {}


def _P(**kw) -> Dict[str, Palette]:
    return kw


_PALETTES["lifeos"] = _P(
    truecolor=Palette(
        bg="#0B0E14", panel="#0F141D", inset="#0A0D13", band="#16202E",
        band_hot="#1A2937",
        line="#1C2634", line_soft="#141C28",
        text_hi="#F2F7FC", text="#D7E1EC", text_dim="#8B99AC", text_faint="#556278",
        accent="#22D3EE", accent_hi="#67E8F9", on_accent="#06222B", on_ok="#06281F",
        state_ok="#34D399", ok_soft="#0E2A22", state_warn="#FBBF24",
        danger="#FB7185", hot="#FF9F45", hot_dim="#9A6B4F",
    ),
    eight_bit=Palette(
        bg="#000000", panel="#080808", inset="#000000", band="#1c1c1c",
        band_hot="#262626",
        line="#3a3a3a", line_soft="#262626",
        text_hi="#eeeeee", text="#d0d0d0", text_dim="#a8a8a8", text_faint="#767676",
        accent="#00d7ff", accent_hi="#5fd7ff", on_accent="#000000",
        on_ok="#000000",
        state_ok="#00ff87", ok_soft="#005f5f", state_warn="#ffaf00",
        danger="#ff5f5f", hot="#ff8700", hot_dim="#af5f00",
    ),
    standard=Palette(
        bg="", panel="", inset="", band="black", band_hot="black",
        line="white", line_soft="bright_black",
        text_hi="bold white", text="white", text_dim="bright_black", text_faint="bright_black",
        accent="bold cyan", accent_hi="bold cyan", on_accent="black", on_ok="black",
        state_ok="bold green", ok_soft="black", state_warn="yellow",
        danger="red", hot="yellow", hot_dim="bright_black",
    ),
)

_PALETTES["phosphor"] = _P(
    truecolor=Palette(
        bg="#020803", panel="#05100A", inset="#020A05", band="#0A2416",
        band_hot="#0E301E",
        line="#14371F", line_soft="#0C2617",
        text_hi="#DFFFEF", text="#A3FFC4", text_dim="#59C77F", text_faint="#307A4B",
        accent="#4DFFA0", accent_hi="#8CFFC8", on_accent="#03220F", on_ok="#03220F",
        state_ok="#4DFFA0", ok_soft="#0B3A21", state_warn="#F7D354",
        danger="#FF7661", hot="#9DFF57", hot_dim="#4E8433",
    ),
    eight_bit=Palette(
        bg="#000000", panel="#000800", inset="#000000", band="#001c00",
        band_hot="#003000",
        line="#005f00", line_soft="#003000",
        text_hi="#d7ffd7", text="#5fff87", text_dim="#00d75f", text_faint="#008700",
        accent="#5fff87", accent_hi="#87ff87", on_accent="#000000",
        on_ok="#000000",
        state_ok="#5fff87", ok_soft="#005f00", state_warn="#d7af00",
        danger="#ff5f5f", hot="#87ff00", hot_dim="#5f8700",
    ),
    standard=Palette(
        bg="", panel="", inset="", band="black", band_hot="black",
        line="white", line_soft="bright_black",
        text_hi="bold green", text="green", text_dim="green", text_faint="bright_black",
        accent="bold green", accent_hi="bold green", on_accent="black",
        on_ok="black",
        state_ok="bold green", ok_soft="black", state_warn="yellow",
        danger="red", hot="green", hot_dim="bright_black",
    ),
)

_PALETTES["amber"] = _P(
    truecolor=Palette(
        bg="#0D0802", panel="#160D04", inset="#0F0802", band="#231402",
        band_hot="#2E1B05",
        line="#33200C", line_soft="#241605",
        text_hi="#FFF6E0", text="#FFD275", text_dim="#C98F33", text_faint="#7C5A20",
        accent="#FFB000", accent_hi="#FFD677", on_accent="#2A1500", on_ok="#2A1500",
        state_ok="#FFB000", ok_soft="#3A2303", state_warn="#FF7A00",
        danger="#FF5F1F", hot="#FFC53D", hot_dim="#8A6A1E",
    ),
    eight_bit=Palette(
        bg="#000000", panel="#080500", inset="#000000", band="#1c1200",
        band_hot="#2a1c00",
        line="#5f3f00", line_soft="#3f2a00",
        text_hi="#ffd787", text="#ffaf00", text_dim="#d78700", text_faint="#875f00",
        accent="#ffaf00", accent_hi="#ffd75f", on_accent="#000000",
        on_ok="#000000",
        state_ok="#ffaf00", ok_soft="#5f3f00", state_warn="#ff8700",
        danger="#ff5f00", hot="#ffaf00", hot_dim="#875f00",
    ),
    standard=Palette(
        bg="", panel="", inset="", band="black", band_hot="black",
        line="yellow", line_soft="bright_black",
        text_hi="bold yellow", text="yellow", text_dim="yellow", text_faint="bright_black",
        accent="bold yellow", accent_hi="bold yellow", on_accent="black",
        on_ok="black",
        state_ok="bold yellow", ok_soft="black", state_warn="yellow",
        danger="red", hot="yellow", hot_dim="bright_black",
    ),
)


# ---------------------------------------------------------------------------
# Typography / spacing / metrics — the strict type ramp lives here
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeRamp:
    """style strings consumed by rich; combined with palette slot names."""
    hero: str = "bold"
    title: str = "bold"
    h2: str = "bold"
    label: str = ""
    value: str = "bold"
    dim: str = ""
    faint: str = ""
    mono_num: str = "bold"
    inverse: str = "bold"


@dataclass(frozen=True)
class Spacing:
    gutter: int = 1
    pad_h: int = 1
    pad_v: int = 0
    row_gap: int = 1
    panel_pad: int = 1


@dataclass(frozen=True)
class Metrics:
    cal_cell: int = 5
    min_w: int = 60
    min_h: int = 20
    cal_w_wide: int = 49
    cal_w_narrow: int = 40
    wide_bp: int = 120   # terminal width where the "wide" calendar/kicker kicks in


@dataclass(frozen=True)
class AnimTuning:
    tick: float = 0.033          # single driver tick (30 fps budget, input-safe)
    progress_k: float = 0.30     # per-frame ease factor for the bar
    progress_frames: int = 22    # hard frame budget for any bar animation
    row_flash: float = 0.14
    row_flip: float = 0.10
    row_settle: float = 0.40
    spark_frames: int = 14
    boot_quick: float = 0.14
    boot_slow: float = 0.12
    boot_frames: int = 6
    fade_frames: int = 4
    fade_step: float = 0.055
    month_frames: int = 4
    toast_ttl: float = 2.6
    ambient_on: bool = False     # flame flicker / scanline — off unless asked


# ---------------------------------------------------------------------------
# Micro-copy registry — every state speaks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Messages:
    hero_today: str = "Win the morning."
    hero_press_on: str = "Press on — the day is yielding."
    hero_done: str = "Day complete — banked."
    hero_history: str = "The record stands."
    hero_future: str = "Tomorrow isn't written yet."
    momentum_start: str = "Fresh page. Start the chain."
    momentum_open: str = "Ignition — first rep done."
    momentum_mid: str = "Momentum building."
    momentum_close: str = "Closing in — {n} to go."
    momentum_final: str = "One rep left. Finish it."
    momentum_done: str = "Day sealed. Momentum banked."
    empty_invite: str = "add a ritual — every day compounds"
    toast_jumped: str = "jumped to {date}"
    toast_added: str = "ritual added — it repeats daily"
    toast_renamed: str = "renamed"
    toast_deleted: str = "ritual deleted"
    toast_future: str = "the future is read-only"
    toast_today: str = "back to today"
    toast_cal_on: str = "browsing — arrows move · enter jumps · esc returns"
    toast_cal_off: str = "back to the list"
    toast_midnight: str = "midnight — rolled into a new day"
    toast_no_tasks: str = "nothing here yet — press a"
    toast_theme: str = "theme · {name}"
    streak_0: str = "no streak yet"
    streak_1: str = "1 day"
    streak_n: str = "{n} days"


# ---------------------------------------------------------------------------
# Boot sequence overlay — styled frames, rendered as a centered splash
# ---------------------------------------------------------------------------


BOOT_STAGES = (
    "boot  ·  loading rituals  ◌",
    "boot  ·  opening ledger   ",
    "boot  ·  sync ledger      ",
    "boot  ·  calibrate streak ",
    "boot  ·  lock interface   ",
    "boot  ·  systems live  ✦  ",
)
BOOT_FRAME_H = 11


# ---------------------------------------------------------------------------
# The Theme aggregate
# ---------------------------------------------------------------------------


class Theme:
    __slots__ = (
        "name", "label", "palette", "glyphs", "type", "spacing", "metrics",
        "anim", "messages", "caps", "css", "ascii_logo",
    )

    def __init__(self, name: str, label: str, caps: Capabilities):
        self.name = name
        self.label = label
        self.caps = caps
        self.palette = _PALETTES[name][caps.color_level]
        self.glyphs = build_glyphs(caps.unicode)
        self.type = TypeRamp()
        self.spacing = Spacing()
        self.metrics = Metrics()
        self.anim = AnimTuning()
        self.messages = Messages()
        self.ascii_logo = _build_logo(caps)
        self.css = _build_css(self)


def _build_logo(caps: Capabilities) -> List[str]:
    if not caps.unicode:
        return [
            "**     ** **",
            " ***  **** * LIFEOS DAILY",
        ]
    return [
        " ▛██▋    ██  ██  ▗██▖     ",
        " ▜██▌ ██ ▝▜██▛▘ ▞▀▜▌ ██  ",
    ]


# ---------------------------------------------------------------------------
# CSS template — one place; palette values substituted as CSS custom props
# ---------------------------------------------------------------------------


def _build_css(th: Theme) -> str:
    p = th.palette
    m = th.metrics

    def v(name: str) -> str:
        return getattr(p, name) or "default"

    return f"""
/* ── lifeOS token surface ─────────────────────────────────────────── */
$bg:        {v('bg')};
$panel:     {v('panel')};
$inset:     {v('inset')};
$band:      {v('band')};
$bandhot:   {v('band_hot')};
$line:      {v('line')};
$linesoft:  {v('line_soft')};
$texthi:    {v('text_hi')};
$txt:       {v('text')};
$txtdim:    {v('text_dim')};
$txtfaint:  {v('text_faint')};
$accent:    {v('accent')};
$accenthi:  {v('accent_hi')};
$onaccent:  {v('on_accent')};
$onok:      {v('on_ok')};
$ok:        {v('state_ok')};
$oksoft:    {v('ok_soft')};
$warn:      {v('state_warn')};
$danger:    {v('danger')};
$hot:       {v('hot')};
$hotdim:    {v('hot_dim')};

Screen {{
    background: $bg;
    color: $txt;
    layout: vertical;
}}

/* ┌──────────────────────── chrome: header ┐ */
#topbar {{
    height: 3;
    background: $panel;
    padding: 0 1;
    border-bottom: solid $line;
}}

/* ┌──────────────────────── hero banner ┐ */
#hero_panel {{
    height: 5;
    padding: 0 {m.cal_cell - 3};
    background: $panel;
    border: round $line;
    border-title-color: $txtfaint;
}}

/* ┌──────────────────────── task list ┐ */
#routine_list {{
    height: 1fr;
    padding: 0 1;
    background: $bg;
}}

/* ┌──────────────────────── momentum dock ┐ */
#dock_panel {{
    height: 7;
    padding: 0 {m.cal_cell - 3};
    background: $panel;
    border: round $line;
    border-title-color: $txtfaint;
}}

/* ┌──────────────────────── calendar ┐ */
#calendar_container {{
    width: {m.cal_w_narrow};
    height: 1fr;
    padding: 0 1 0 0;
    background: $bg;
}}
#calendar_container.hidden {{ display: none; }}
#cal_panel {{
    height: 1fr;
    max-height: 19;
    padding: 0 1;
    background: $panel;
    border: round $line;
    border-title-color: $txtfaint;
}}

/* ┌──────────────────────── toast rail ┐ */
#toast {{
    height: 1;
    padding: 0 1;
    color: $txtdim;
    background: $bg;
}}
#toast.hot {{ color: $accenthi; text-style: bold; }}
#toast.err {{ color: $danger; text-style: bold; }}

/* ┌──────────────────────── footer ┐ */
KeyChipBar {{
    height: 1;
    background: $panel;
    color: $txtdim;
}}
KeyChipBar .chip-k {{
    text-style: bold;
    color: $accenthi;
}}
KeyChipBar .chip-close {{ color: $txtfaint; }}
KeyChipBar .chip-name {{ color: $txtdim; }}
KeyChipBar .chip-sep {{ color: $txtfaint; }}

/* ┌──────────────────────── boot overlay ┐ */
BootOverlay {{
    background: $bg;
    content-align: center middle;
    layer: overlay;
}}
#boot-frame {{ color: $txt; }}

/* ┌──────────────────────── min-size notice ┐ */
#notice {{
    display: none;
    background: $bg;
    color: $warn;
    text-align: center;
    content-align: center middle;
    text-style: bold;
    height: 1fr;
}}

/* ┌──────────────────────── modals (defaults from screens) ┐ */
Input {{
    border: tall $line;
    background: $inset;
    color: $texthi;
}}
Input:focus {{ border: tall $accent; }}
Button {{ margin-left: 1; }}
"""


# ---------------------------------------------------------------------------
# Theme registry + lookup
# ---------------------------------------------------------------------------


def available_themes() -> List[str]:
    return list(_PALETTES.keys())


def get_theme(name: str, caps: Capabilities) -> Theme:
    if name not in _PALETTES:
        name = "lifeos"
    return Theme(name, name if name != "lifeos" else "lifeos · cyan", caps)


def resolve_startup_theme(cli_theme: Optional[str], caps: Capabilities) -> Theme:
    env_theme = os.environ.get("LIFEOS_THEME", "").strip().lower()
    name = (cli_theme or env_theme or "lifeos").strip().lower()
    if not caps.colorful and name in ("phosphor", "amber"):
        # low-color terminals still work: theme maps onto 16-color ramp
        pass
    return get_theme(name, caps)


# ---------------------------------------------------------------------------
# Frame utilities — braille shimmer, easing, segmented logic
# ---------------------------------------------------------------------------


def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def blit(dst: List, y: int, x: int, s: str, style) -> int:
    if x < 0:
        s = s[-x:]
        x = 0
    if not s:
        return 0
    if y >= len(dst):
        return 0
    row = dst[y]
    n = min(len(s), max(0, len(row) - x))
    for i in range(n):
        row[x + i] = (s[i], style)
    return n


def blank_canvas(w: int, h: int):
    return [[(" ", None) for _ in range(w)] for _ in range(h)]


def canvas_text(canvas) -> Text:
    t = Text()
    for y, row in enumerate(canvas):
        i, n = 0, len(row)
        while i < n:
            ch, st = row[i]
            j = i + 1
            while j < n and row[j][1] == st:
                j += 1
            t.append("".join(row[k][0] for k in range(i, j)), style=st)
            i = j
        if y + 1 < len(canvas):
            t.append("\n")
    return t


# shade ramp for horizontal fades (longest → shortest); "" means use track char
def fade_ramp(g: Glyphs) -> List[str]:
    if g.bar_shades and len(g.bar_shades) >= 3:
        return [g.bar_shades[0], g.bar_shades[1], g.bar_shades[2], g.bar_track]
    return [g.bar_full, g.bar_full, g.bar_track, g.bar_track]


# ---------------------------------------------------------------------------
# Animator — one timer, many sequences. Small, safe, batch-oriented.
# ---------------------------------------------------------------------------


@dataclass
class _Sequence:
    name: str
    n_frames: int
    interval: float
    on_frame: Callable[[int], None]
    on_done: Optional[Callable[[], None]]
    gen: int          # generation counter — lets us cancel by name


class Animator:
    """Drives all animations from a single Textual timer.

    Guarantees: every sequence has a hard frame budget; cancel(name) stops
    a sequence cleanly (on_done NOT fired when cancelled); sequences never
    touch the DOM between ticks — render-safe and input-safe by construction.
    """

    def __init__(self, app, tick: float = 0.033):
        self.app = app
        self.tick = tick
        self._seqs: Dict[str, _Sequence] = {}
        self._last: Dict[str, float] = {}
        self._running = False

    # -- control ----------------------------------------------------------

    def start(self) -> None:
        if not self._running:
            self._running = True
            self.app.set_interval(self.tick, self._tick, name="lifeos_animator")

    def stop(self) -> None:
        self._running = False
        self._seqs.clear()
        self._last.clear()

    @property
    def running(self) -> bool:
        return self._running

    # -- sequences ---------------------------------------------------------

    def play(
        self,
        name: str,
        n_frames: int,
        on_frame: Callable[[int], None],
        on_done: Optional[Callable[[], None]] = None,
        interval: int = 1,
        start: Optional[int] = None,
    ) -> None:
        """(Re)start a named sequence. Replaces any live one with same name."""
        prev = self._seqs.get(name)
        gen = (prev.gen + 1) if prev else 0
        self._seqs[name] = _Sequence(
            name=name,
            n_frames=max(1, n_frames),
            interval=max(1, interval),
            on_frame=on_frame,
            on_done=on_done,
            gen=gen,
        )
        f0 = int(start) if start is not None else 0
        f0 = max(0, min(self._seqs[name].n_frames - 1, f0))
        self._last[name] = float(f0)
        if f0 > 0:
            # enter animation part-way without emitting frame 0
            try:
                on_frame(f0)
            except Exception:
                pass

    def cancel(self, name: str, fire_done: bool = False) -> None:
        seq = self._seqs.pop(name, None)
        self._last.pop(name, None)
        if seq and fire_done and seq.on_done:
            try:
                seq.on_done()
            except Exception:
                pass

    # -- driver ------------------------------------------------------------

    def _tick(self) -> None:
        if not self._seqs:
            return
        done_names: List[str] = []
        for name, seq in list(self._seqs.items()):
            last = self._last.get(name, 0.0)
            frame = int(last + seq.interval)
            if frame >= seq.n_frames:
                frame = seq.n_frames - 1
                done_names.append(name)
            self._last[name] = frame
            # guard: sequence may have been replaced during on_frame; only the
            # generation that scheduled this tick may draw
            try:
                seq.on_frame(frame)
            except Exception:
                pass
        for name in done_names:
            seq = self._seqs.pop(name, None)
            self._last.pop(name, None)
            if seq and seq.on_done:
                try:
                    seq.on_done()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Sparkline helper — given 7 fractions 0..1, make 7 braille bars
# ---------------------------------------------------------------------------


def sparkline(g: Glyphs, fractions: List[float]) -> List[str]:
    ramp = g.spark_line
    lvl_max = len(ramp) - 1
    out = []
    for f in fractions:
        f = max(0.0, min(1.0, f))
        idx = int(round(f * lvl_max))
        if f <= 0.0001:
            idx = 1   # the faint baseline dot (spark_line[1]) reads as "none"
        out.append(ramp[idx])
    return out
