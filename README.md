# lifeOS — Intent-to-Execution Terminal Operating System

> A local-first terminal execution system that converts weekly outcomes into daily commitments, turns commitments into protected focus blocks, records the truth, and uses that history to make tomorrow more realistic.

---

## ⚡ Key Highlights

- **Zero-latency local-first execution**: Instant keyboard interactions powered by Textual and SQLite.
- **Intent-to-Execution Hierarchy**: Areas → Projects → Outcomes → Actions → Time Blocks.
- **Today Command Center**: Single actionable NOW card, Today's Three priority commitments, capacity budgeting, and compact routines strip.
- **Operational Plan Timeline**: Visual schedule with 1-keystroke scheduling (`B`), auto-buffers, and collision prevention.
- **Focus Cockpit**: Distraction-free countdown timer, live session notes, and quick thought capture.
- **Missed Block Handling**: Explicit choice (`[R]` reschedule, `[S]` shrink, `[C]` cancel) — reality always enters the system.
- **Sunday Weekly Review**: Deep work analytics, failure pattern clusters, and actionable decisions.
- **Cognitive AI Copilot**: Narrow AI drafts powered by OpenRouter (`google/gemini-2.5-flash-lite` or custom) with human-in-the-loop review.
- **Cloud Sync & Supabase Realtime**: WebSocket change subscriptions + offline outbox queue + conflict-safe journal preservation.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.8+ (tested on Python 3.14)
- Terminal with truecolor / 256-color support

### Installation
```bash
git clone https://github.com/AdarshJ173/ajtui.git
cd ajtui
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running lifeOS
```bash
# Launch the app
python -m lifeos

# With a specific theme
python -m lifeos --theme phosphor   # or 'lifeos', 'amber'

# Backwards-compatible launcher
python daily.py
```

---

## ⌨️ Core Keybindings

| Key | Action |
|:---|:---|
| `:` | Open Command Palette (`:today`, `:plan`, `:projects`, `:review`, `:ai`, `:sync`, `:theme`) |
| `?` | Help overlay (searchable keybindings) |
| `Space` / `Enter` | Toggle task / action / block |
| `B` | Block / schedule selected action into calendar |
| `I` | Global Quick Capture (Inbox / Project / Next Action) |
| `X` | 90-second Daily Close reflection |
| `W` | Weekly Review (Sunday retrospective) |
| `J` | Open plain-text daily journal |
| `U` | Undo last deletion (5s window) |
| `S` | Force cloud sync |
| `T` | Cycle visual theme |
| `Q` | Quit |

---

## 🧪 Testing & Verification

```bash
# Run the complete pytest test suite (31 tests)
pytest -q

# Run the end-to-end execution OS loop demo
python demo_v3_loop.py
```
