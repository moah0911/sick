# Design — Sick TUI

Mode: **Operate** (task tool). Scanability and precision outrank expression.

## Identity

A precision instrument, print-inspired. Sharp corners, hairline rules,
small-caps labels, tabular alignment. Depth comes from layered values,
never shadows or gradients. No purple/blue gradients, no chat bubbles,
no emoji decoration. Color is semantic or it is absent.

## Tokens

| Token | Value | Use |
|---|---|---|
| background | `#0B0E13` | app base |
| surface | `#12161D` | chat, input |
| panel | `#161C26` | header, sidebar, footer |
| foreground | `#D8DEE9` | primary text |
| muted | `#8A94A6` | secondary text, tool lines |
| primary (emerald) | `#3ECF8E` | active, success, current phase |
| accent (teal) | `#3FB6A8` | user role, links |
| warning (amber) | `#E0B341` | attention, pending |
| error | `#E5534B` | failures, blocked gate |

## Components

- **Messages:** left rule (`▌`) + small-caps role label; agent replies in
  Markdown with syntax-highlighted code. No bubbles.
- **Tool feed:** tree glyphs — `├─ ▸ tool(args)` on start, `╰─ ✓ tool · 0.3s`
  on completion (✗ in error color). Verbatim Sick tool names, never renamed.
- **Thinking:** `THINKING` hairline label, dim italic body, subordinate to
  the reply. Toggle: `/thinking`.
- **SDLC tracker (sidebar):** vertical stepper
  requirements → design → implement → verify → deliver; `✓` done,
  `●` current (emerald), `○` pending; gate line shows DELIVERABLE /
  BLOCKED + first reason in semantic color; tier + routed skill named.
- **Status bar:** structured fields — workspace · branch · state pill
  (`● READY` / `◐ WORKING Ns`) · turns · tools. Not a sentence.
- **Composer:** tall emerald border when focused; model/provider named in
  the border title area; hints quiet in the subtitle.

## Motion

Only the 1s working-state tick and the height-1 indicator row. Restraint
is the premium signal here.
