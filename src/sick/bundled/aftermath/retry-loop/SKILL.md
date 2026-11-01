---
name: retry-loop
description: >
  Use when the same error message recurs after a fix attempt, or this is the
  2nd+ try at the same fix. Stop varying the fix, state the exact error and
  the theory, then ask instead of trying a third variation. Includes an
  attempt-ledger protocol.
license: MIT
---

# Retry Loop

Same error twice means the theory is wrong, not the formatting.

## Attempt ledger

Keep one line per attempt. The distinction that matters:

- Same error, no edit in between → same attempt. Re-running did not test a new theory.
- Same error after an edit → 2nd failed attempt. Stop here.
- Green test, `/aftermath-revert`, or `/aftermath off` → ledger resets.

Format:

```
attempt 1 | changed: [hunk/flag] | error: [exact] | proved: [what it ruled out]
attempt 2 | changed: [hunk/flag] | error: [exact] | proved: [what it ruled out]
```

## Steps

1. Stop. No third variation.
2. Paste the exact error verbatim — not a paraphrase. Trim only repeated stack frames.
3. State the current theory in one line, labeled as theory until verified.
4. State what was already tried (attempt 1, attempt 2) and what each attempt proved.
5. Ask: confirm the theory with the user, or request the missing fact (log, version, repro step) instead of guessing it.
6. One deliberate next step only after the answer. If it fails identically, return to step 2 — do not widen scope.

## Forbidden

- Varying imports, flags, or syntax hoping the error changes shape.
- Filling a missing fact with a guess.
- Touching files outside the failing path to "see if it helps".
- Re-running the same command and calling it a new attempt.
- Disguising a command to get past an enforcement block.

Gap-filling must be said out loud. If the second attempt fails identically, the next move is a question, not attempt three.
