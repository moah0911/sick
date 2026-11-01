# AFTERMATH — post-failure recovery ladder

Stop. Read this before your next edit. First rung that holds wins.

1. Uncommitted / one file / cheap to undo? → Revert now. Do not patch forward.
2. Last-known-good exists (passing test, last commit)? → Diff it, isolate one change, revert just that.
3. 2nd+ failed attempt at same fix? → Stop varying. State exact error, state theory, ask.
4. Next action irreversible (force push, drop, delete, overwrite)? → Confirm state explicitly. Never assume.
5. Filling a gap with a guess? → Say so out loud. Never continue silently.
6. User just corrected you ("you broke it")? → Do not defend. Find the diff. Fix only that.

Honesty: never hide a break. Never silently revert. Never invent an unverified root cause.
