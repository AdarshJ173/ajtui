"""
lifeOS Theme Engine & Visual Design System
==========================================
Unified source of truth for visual tokens, palettes, glyph sets, animations, and CSS.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from rich.text import Text


# ---------------------------------------------------------------------------
# Capability detection
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
    """True when the locale advertises UTF-8."""
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
        e = os.environ if env is None else env
        self.reduced_motion: bool = bool(
            e.get("LIFEOS_NO_MOTION")
            or e.get("NO_MOTION")
            or (e.get("REDUCE_MOTION", "") or "").lower() in ("1", "true", "yes")
        )

    @property
    def colorful(self) -> bool:
        return self.color_level != "standard"


# ---------------------------------------------------------------------------
# Glyph sets — Unicode with ASCII fallbacks
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
    bar_right: str
    bar_full: str
    bar_shades: str
    bar_track: str
    spark_line: str
    flame: str
    bolt: str
    done: str
    partial: str
    empty: str
    w_right: str
    enter: str
    journal: str
    cloud_live: str
    cloud_syncing: str
    cloud_offline: str
    cloud_conflict: str


_GLYPH_TABLE: Dict[str, tuple] = {
    # field            unicode            ascii
    "logo":            ("◆",               "*"),
    "spark":           ("✦",               "*"),
    "check":           ("✓",               "x"),
    "check_flash":     ("✔",               "#"),
    "open_box":        ("○",               "o"),
    "squared":         ("▪",               "#"),
    "line_v":          ("│",               "|"),
    "bar_left":        ("▐",               "["),
    "bar_right":       ("▌",               "]"),
    "bar_full":        ("█",               "#"),
    "bar_shades":      ("▓▒░",             "#+."),
    "bar_track":       ("·",               "."),
    "spark_line":      (" ▁▂▃▄▅▆",         " ._-^~"),
    "flame":           ("♦",               "^"),
    "bolt":            ("»",               ">"),
    "done":            ("●",               "o"),
    "partial":         ("◐",               "%"),
    "empty":           ("·",               "."),
    "w_right":         ("▸",               ">"),
    "enter":           ("↵",               "R"),
    "journal":         ("▪",               "j"),
    "cloud_live":      ("☁",               "~"),
    "cloud_syncing":   ("↻",               "*"),
    "cloud_offline":   ("⊘",               "-"),
    "cloud_conflict":  ("⚠",               "!"),
}


def build_glyphs(uni: bool) -> Glyphs:
    return Glyphs(**{k: (v[0] if uni else v[1]) for k, v in _GLYPH_TABLE.items()})


# ---------------------------------------------------------------------------
# Semantic Palettes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
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
    state_ok: str
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
        accent="#22D3EE", accent_hi="#67E8F9", on_accent="#06222B",
        state_ok="#34D399", state_warn="#FBBF24",
        danger="#FB7185", hot="#FF9F45", hot_dim="#9A6B4F",
    ),
    eight_bit=Palette(
        bg="#000000", panel="#080808", inset="#000000", band="#1c1c1c",
        band_hot="#262626",
        line="#3a3a3a", line_soft="#262626",
        text_hi="#eeeeee", text="#d0d0d0", text_dim="#a8a8a8", text_faint="#767676",
        accent="#00d7ff", accent_hi="#5fd7ff", on_accent="#000000",
        state_ok="#00ff87", state_warn="#ffaf00",
        danger="#ff5f5f", hot="#ff8700", hot_dim="#af5f00",
    ),
    standard=Palette(
        bg="", panel="", inset="", band="black", band_hot="black",
        line="white", line_soft="bright_black",
        text_hi="bold white", text="white", text_dim="bright_black",
        text_faint="bright_black",
        accent="bold cyan", accent_hi="bold cyan", on_accent="black",
        state_ok="bold green", state_warn="yellow",
        danger="red", hot="yellow", hot_dim="bright_black",
    ),
)

_PALETTES["phosphor"] = _P(
    truecolor=Palette(
        bg="#020803", panel="#05100A", inset="#020A05", band="#0A2416",
        band_hot="#0E301E",
        line="#14371F", line_soft="#0C2617",
        text_hi="#DFFFEF", text="#A3FFC4", text_dim="#59C77F", text_faint="#307A4B",
        accent="#4DFFA0", accent_hi="#8CFFC8", on_accent="#03220F",
        state_ok="#4DFFA0", state_warn="#F7D354",
        danger="#FF7661", hot="#9DFF57", hot_dim="#4E8433",
    ),
    eight_bit=Palette(
        bg="#000000", panel="#000800", inset="#000000", band="#001c00",
        band_hot="#003000",
        line="#005f00", line_soft="#003000",
        text_hi="#d7ffd7", text="#5fff87", text_dim="#00d75f", text_faint="#008700",
        accent="#5fff87", accent_hi="#87ff87", on_accent="#000000",
        state_ok="#5fff87", state_warn="#d7af00",
        danger="#ff5f5f", hot="#87ff00", hot_dim="#5f8700",
    ),
    standard=Palette(
        bg="", panel="", inset="", band="black", band_hot="black",
        line="white", line_soft="bright_black",
        text_hi="bold green", text="green", text_dim="green",
        text_faint="bright_black",
        accent="bold green", accent_hi="bold green", on_accent="black",
        state_ok="bold green", state_warn="yellow",
        danger="red", hot="green", hot_dim="bright_black",
    ),
)

_PALETTES["amber"] = _P(
    truecolor=Palette(
        bg="#0D0802", panel="#160D04", inset="#0F0802", band="#231402",
        band_hot="#2E1B05",
        line="#33200C", line_soft="#241605",
        text_hi="#FFF6E0", text="#FFD275", text_dim="#C98F33", text_faint="#7C5A20",
        accent="#FFB000", accent_hi="#FFD677", on_accent="#2A1500",
        state_ok="#FFB000", state_warn="#FF7A00",
        danger="#FF5F1F", hot="#FFC53D", hot_dim="#8A6A1E",
    ),
    eight_bit=Palette(
        bg="#000000", panel="#080500", inset="#000000", band="#1c1200",
        band_hot="#2a1c00",
        line="#5f3f00", line_soft="#3f2a00",
        text_hi="#ffd787", text="#ffaf00", text_dim="#d78700", text_faint="#875f00",
        accent="#ffaf00", accent_hi="#ffd75f", on_accent="#000000",
        state_ok="#ffaf00", state_warn="#ff8700",
        danger="#ff5f00", hot="#ffaf00", hot_dim="#875f00",
    ),
    standard=Palette(
        bg="", panel="", inset="", band="black", band_hot="black",
        line="yellow", line_soft="bright_black",
        text_hi="bold yellow", text="yellow", text_dim="yellow",
        text_faint="bright_black",
        accent="bold yellow", accent_hi="bold yellow", on_accent="black",
        state_ok="bold yellow", state_warn="yellow",
        danger="red", hot="yellow", hot_dim="bright_black",
    ),
)

THEME_LABELS = {
    "lifeos": "lifeos · cyan",
    "phosphor": "phosphor · green",
    "amber": "amber · mono",
}


# ---------------------------------------------------------------------------
# Typography & Metrics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TypeRamp:
    hero: str = "bold"
    title: str = "bold"
    value: str = "bold"
    dim: str = ""
    faint: str = ""


@dataclass(frozen=True)
class Spacing:
    gutter: int = 1
    pad_h: int = 1
    row_gap: int = 1
    panel_pad: int = 1


@dataclass(frozen=True)
class Metrics:
    min_w: int = 58
    min_h: int = 20
    cal_w: int = 38
    stack_bp: int = 84
    list_h_stacked: int = 12


@dataclass(frozen=True)
class AnimTuning:
    tick: float = 0.033
    progress_frames: int = 18
    flip_frames: int = 8
    boot_frames: int = 13
    toast_ttl: float = 2.6
    ambient_period: float = 1.0


# ---------------------------------------------------------------------------
# Micro-copy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Messages:
    hero_today: str = "Win the morning."
    hero_press_on: str = "Press on — the day is yielding."
    hero_done: str = "Day complete — banked."
    hero_history: str = "The record stands."
    hero_future: str = "Tomorrow isn't written yet."
    sub_today_zero: str = "{total} rituals waiting. First step sets the momentum."
    sub_today_mid: str = "{done} of {total} completed. Finish the remaining {left} to secure the day."
    sub_done: str = "All daily rituals completed. Full discipline achieved today."
    sub_history: str = "Record archived. Completed {done}/{total} routines ({pct}%)."
    sub_future: str = "Plan your intentions ahead. The future is read-only — calm, not locked."
    momentum_start: str = "Fresh page. Start the chain."
    momentum_open: str = "Ignition — first rep done."
    momentum_mid: str = "Momentum building."
    momentum_close: str = "Closing in — {n} to go."
    momentum_final: str = "One rep left. Finish it."
    momentum_done: str = "Day sealed. Momentum banked."
    empty_title: str = "This page of the ledger is blank."
    empty_invite: str = "add your first ritual — every day compounds"
    empty_hint: str = "[A]"
    toast_jumped: str = "jumped to {date}"
    toast_added: str = "ritual added — it repeats daily"
    toast_renamed: str = "renamed to “{title}”"
    toast_deleted: str = "ritual deleted"
    toast_done: str = "banked · {title}"
    toast_undone: str = "returned to the queue · {title}"
    toast_future: str = "the future is read-only"
    toast_today: str = "back to today"
    toast_cal_on: str = "browsing — arrows move · enter jumps · esc returns"
    toast_cal_off: str = "back to the list"
    toast_no_tasks: str = "nothing here yet — press a"
    toast_theme: str = "theme · {name}"
    toast_moved: str = "moved {dir} · {title}"
    toast_journal_saved: str = "journal saved · {words} words"
    toast_journal_deleted: str = "journal entry deleted"
    toast_sync_forced: str = "syncing with Supabase…"
    toast_sync_done: str = "cloud sync complete"
    toast_sync_offline: str = "offline · working locally"
    toast_conflict: str = "conflict resolved · saved backup to conflicts/"


BOOT_STAGES = (
    "loading rituals",
    "opening ledger",
    "syncing completions",
    "calibrating streak",
    "locking interface",
    "systems live",
)


class Theme:
    __slots__ = (
        "name", "label", "palette", "glyphs", "type", "spacing", "metrics",
        "anim", "messages", "caps", "css", "ascii_logo",
    )

    def __init__(self, name: str, caps: Capabilities):
        self.name = name
        self.label = THEME_LABELS.get(name, name)
        self.caps = caps
        self.palette = _PALETTES.get(name, _PALETTES["lifeos"])[caps.color_level]
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
            ".  _   .",
            "|_|_| |_|  LIFEOS",
        ]
    return [
        "▖  ▗ ▖  ▗",
        "▙▟▙▟▙▟▙▟",
    ]


_RICH_TO_CSS_COLOR = {
    "bright_black": "ansi_bright_black",
    "bright_white": "ansi_bright_white",
    "bright_red": "ansi_bright_red",
    "bright_green": "ansi_bright_green",
    "bright_yellow": "ansi_bright_yellow",
    "bright_blue": "ansi_bright_blue",
    "bright_magenta": "ansi_bright_magenta",
    "bright_cyan": "ansi_bright_cyan",
}


def css_color(token: str) -> str:
    if not token:
        return "ansi_default"
    last = token.split()[-1]
    return _RICH_TO_CSS_COLOR.get(last, last)


def rich_style(token: str) -> tuple[str, str]:
    parts = token.split()
    attrs, color = parts[:-1], parts[-1] if parts else ""
    return " ".join(attrs), color


def _build_css(th: Theme) -> str:
    p = th.palette
    m = th.metrics

    def v(name: str) -> str:
        return css_color(getattr(p, name))

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
$ok:        {v('state_ok')};
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
    padding: 1 1 0 1;
    border-bottom: solid $line;
}}

/* ┌──────────────────────── hero banner ┐ */
#hero_panel {{
    height: auto;
    max-height: 6;
    padding: 1 2;
    margin: 1 1 0 1;
    background: $panel;
    border: round $line;
}}

/* ┌──────────────────────── main split ┐ */
#main_content {{
    height: 1fr;
    layout: horizontal;
    padding: 0 1;
}}
#main_content.stacked {{
    layout: vertical;
}}

/* ┌──────────────────────── task list ┐ */
#routine_list {{
    width: 1fr;
    height: 1fr;
    padding: 0 1;
    background: $bg;
    border: round $line;
    border-title-color: $txtfaint;
}}
#main_content.stacked #routine_list {{
    height: {m.list_h_stacked};
}}

/* ┌──────────────────────── calendar rail ┐ */
#calendar_container {{
    width: {m.cal_w};
    height: 1fr;
    padding-left: 1;
    background: $bg;
}}
#calendar_container.hidden {{ display: none; }}
#cal_panel {{
    height: auto;
    padding: 0 2 1 2;
    background: $panel;
    border: round $line;
    border-title-color: $txtfaint;
}}

/* ┌──────────────────────── momentum dock ┐ */
#dock_panel {{
    height: auto;
    max-height: 7;
    padding: 1 2;
    margin: 0 1 1 1;
    background: $panel;
    border: round $line;
    border-title-color: $txtfaint;
}}

/* ┌──────────────────────── toast rail ┐ */
#toast {{
    height: 1;
    padding: 0 2;
    color: $txtdim;
    background: $bg;
}}

/* ┌──────────────────────── footer ┐ */
#footer {{
    height: 1;
    background: $panel;
    color: $txtdim;
    padding: 0 1;
}}

/* ┌──────────────────────── journal view ┐ */
#journal_container {{
    width: 1fr;
    height: 1fr;
    padding: 1 2;
    margin: 1 1 0 1;
    background: $panel;
    border: round $line;
    layout: vertical;
}}

#journal_header {{
    height: 3;
    padding: 0 1;
    border-bottom: solid $line;
}}

#journal_reader {{
    width: 1fr;
    height: 1fr;
    padding: 1 1;
    background: $inset;
    border: round $line;
    overflow-y: scroll;
}}

#journal_editor {{
    width: 1fr;
    height: 1fr;
    background: $inset;
    border: round $accent;
    color: $texthi;
}}

#journal_browse_list {{
    width: 1fr;
    height: 1fr;
    padding: 1 1;
    background: $inset;
    border: round $line;
}}

/* ┌──────────────────────── boot overlay ┐ */
#boot_layer {{
    background: $bg;
    content-align: center middle;
    layer: overlay;
    width: 100%;
    height: 100%;
}}

/* ┌──────────────────────── modals ┐ */
Input {{
    border: tall $line;
    background: $inset;
    color: $texthi;
}}
Input:focus {{ border: tall $accent; }}
TextArea {{
    border: tall $line;
    background: $inset;
    color: $texthi;
}}
TextArea:focus {{ border: tall $accent; }}
Button {{ margin-left: 1; }}
"""


def available_themes() -> List[str]:
    return list(_PALETTES.keys())


def get_theme(name: str, caps: Capabilities) -> Theme:
    if name not in _PALETTES:
        name = "lifeos"
    return Theme(name, caps)


def resolve_startup_theme(cli_theme: Optional[str], caps: Capabilities) -> Theme:
    env_theme = os.environ.get("LIFEOS_THEME", "").strip().lower()
    name = (cli_theme or env_theme or "lifeos").strip().lower()
    return get_theme(name, caps)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c = 1.70158
    return 1.0 + (c + 1.0) * ((t - 1.0) ** 3) + c * ((t - 1.0) ** 2)


_EIGHTHS = " ▏▎▍▌▋▊▉█"


def progress_bar_cells(frac: float, width: int, unicode: bool) -> List[str]:
    frac = max(0.0, min(1.0, frac))
    width = max(1, width)
    if not unicode:
        filled = int(round(frac * width))
        return ["#"] * filled + ["."] * (width - filled)
    total_eighths = int(round(frac * width * 8))
    full, rem = divmod(total_eighths, 8)
    full = min(full, width)
    cells: List[str] = ["█"] * full
    if full < width:
        cells.append(_EIGHTHS[rem] if rem else "·")
        cells.extend(["·"] * (width - full - 1))
    return cells[:width]


def sparkline(g: Glyphs, fractions: List[float]) -> str:
    ramp = g.spark_line
    lvl_max = len(ramp) - 1
    out = []
    for f in fractions:
        f = max(0.0, min(1.0, f))
        idx = int(round(f * lvl_max))
        if f <= 0.0001:
            idx = 1
        out.append(ramp[idx])
    return "".join(out)


def dotgrid(fractions: List[float], filled: str, empty: str) -> str:
    return "".join((filled if f >= 0.999 else empty) for f in fractions)


@dataclass
class _Sequence:
    name: str
    n_frames: int
    interval: int
    on_frame: Callable[[int], None]
    on_done: Optional[Callable[[], None]]
    gen: int


class Animator:
    """Frame-batched animator from a single timer."""

    def __init__(self, app, tick: float = 0.033):
        self.app = app
        self.tick = tick
        self._seqs: Dict[str, _Sequence] = {}
        self._last: Dict[str, float] = {}
        self._running = False

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

    def play(
        self,
        name: str,
        n_frames: int,
        on_frame: Callable[[int], None],
        on_done: Optional[Callable[[], None]] = None,
        interval: int = 1,
    ) -> None:
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
        self._last[name] = -1.0

    def cancel(self, name: str, fire_done: bool = False) -> None:
        seq = self._seqs.pop(name, None)
        self._last.pop(name, None)
        if seq and fire_done and seq.on_done:
            try:
                seq.on_done()
            except Exception:
                pass

    def _tick(self) -> None:
        if not self._seqs:
            return
        done_names: List[str] = []
        for name, seq in list(self._seqs.items()):
            if self._seqs.get(name) is not seq:
                continue
            last = self._last.get(name, -1.0)
            frame = int(last + seq.interval)
            if frame >= seq.n_frames - 1:
                frame = seq.n_frames - 1
                done_names.append(name)
            self._last[name] = float(frame)
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


def fit(text: str, width: int, ellipsis: str = "…") -> str:
    if width < 1:
        return ""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + ellipsis


def dim_style(base: str) -> str:
    return f"dim {base}" if base else "dim"
