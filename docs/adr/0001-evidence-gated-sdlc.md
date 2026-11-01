# 0001: Evidence-gated SDLC instead of prompt-based SDLC

## Status

Accepted

## Context

Sick claimed "SDLC & OO, always active," but the implementation was a
9-line prompt string (`SDLC_PROMPT`) the LLM was free to ignore, and
`SickAgent.handle()` recorded every turn's experience as `"success"`
unconditionally. Tools returned `str`/`bool`/`list` inconsistently, so
the agent type-sniffed output prefixes to guess success. There was no
proof the agent followed any phase, and no way to audit a task after
the fact.

Alternatives considered: (a) stronger prompting — rejected, still
unenforceable and unauditable; (b) hard gates for every task —
rejected, punishes trivial questions with process; (c) advisory
warnings — rejected, identical to prompting with extra steps.

## Decision

Implement SDLC as a runtime lifecycle (`sick.lifecycle.Lifecycle`):

- Phases are **observed from real tool results** (exploration →
  design, mutation → implement, passing verification after the last
  mutation → verify), not self-reported by the LLM.
- Delivery is a **runtime gate** (`can_deliver`): STANDARD runs need
  verification evidence after the last edit; RISKY runs additionally
  need approval (`/plan` → `/approve`) and a checkpoint. Trivial runs
  fast-path. The LLM cannot override a failing gate.
- Every tool returns one type, **`ToolResult`**, dispatched through
  `ToolRegistry` (audit, counts, lifecycle recording behind one seam).
- Every run persists artifacts under `.sick/runs/<id>/`
  (requirements/design/plan/verification/summary), and changed Python
  files get deterministic AST design checks (duplicate definitions
  block; size/private-access findings are recorded).
- Phases route installed skills (`codebase-design` for design, `tdd`
  for verify, ...) through the existing skill discovery.

## Consequences

- "Done" becomes falsifiable: a blocked run leaves a `verification.json`
  naming the exact missing evidence. `/learn` mines blocked runs.
- Tool authors must return `ToolResult`; direct `execute()` callers use
  `.output`/`.ok`. Agent proxy methods keep rendering plain values to
  the LLM, so NOOA CodeAct behaviour is unchanged.
- Risk classification is heuristic (paths, tool choice, file count).
  False RISKY classifications cost an approval + checkpoint, never a
  silent pass — the failure direction is deliberate.
