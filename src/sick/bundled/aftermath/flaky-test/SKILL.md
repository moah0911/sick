---
name: flaky-test
description: >
  Use when the same test alternates between pass and fail without code edits,
  or when a failure cannot be reproduced. Rerun to confirm, find the source of
  nondeterminism, and never revert working code on an unconfirmed flake.
license: MIT
---

# Flaky Test

A test that changes its mind is evidence about the test or its environment, not about your last edit.

## Confirm before you act

1. Stop. Do not revert or edit yet.
2. Re-run the exact same test command. Capture each outcome.
3. Pass/fail flips with no edit in between → flaky suspected. State the sequence explicitly, for example `pass → fail → pass`.
4. Check the usual sources of nondeterminism, in this order:
   - time and timezone (`Date.now`, `TZ`, frozen clocks)
   - ordering and shared state (test isolation, parallel workers)
   - randomness and seeds (`Math.random`, faker, randomized fixtures)
   - network, ports, and external services
   - filesystem state left by an earlier run
5. Label the suspected source as theory until a repeat/seed/isolate experiment proves it.
6. Fix the nondeterminism, not the assertion. Do not delete the test to get green.

## Plugin behavior

- The outcome tracker flags `pass → fail → pass` (or the reverse) with no editing between runs.
- A flaky signal suppresses checkpoint auto-revert and does not freeze forward edits; rerunning is the next action.
- The signal is one-shot. If the next run passes cleanly, stand down.

## Never

- Never claim a flake without at least one rerun.
- Never weaken or skip an assertion to make a flake disappear.
- Never mix a flake fix with unrelated changes.
- Never use a flaky result as justification for a broad refactor.
