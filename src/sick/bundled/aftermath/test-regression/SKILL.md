---
name: test-regression
description: >
  Use when a test suite goes green to red after an edit, or a previously
  passing test starts failing. Diff against last-known-good, isolate the one
  change, revert just that hunk instead of patching around it. Includes
  runner-specific failure signatures, subset re-runs, and checkpoint behavior.
license: MIT
---

# Test Regression

A green suite just turned red. The edit caused it until proven otherwise.

## Steps

1. Stop. No new edits.
2. State what broke: which runner, which suite, which tests, what the last edit touched. One line each.
3. Find last-known-good: last passing run, last commit, or the `ultra` checkpoint.
4. `git diff` against it. Isolate the single hunk that correlates with the failure.
5. Revert just that hunk (at `lite`, propose it and wait; at `full`, ask before the next edit; at `ultra` with `autoRevert: true`, the plugin may already have restored it — verify the diff).
6. Re-run the failing subset only. Green → stand down. Still red → escalate to `retry-loop`, do not vary the fix blindly.

## Runner signatures and subset re-runs

| Runner | Failure signature | Re-run the subset |
|--------|-------------------|-------------------|
| pytest | `FAILED tests/...`, `1 failed`, `Traceback` | `pytest tests/test_auth.py::test_login -q` |
| Jest / Vitest | `✕`, `1 failed`, `FAIL` | `npx jest auth.spec -t "login"` |
| Go | `--- FAIL: TestLogin` | `go test ./pkg/auth -run TestLogin -v` |
| Cargo | `test result: FAILED`, `panicked at` | `cargo test auth::login -- --nocapture` |
| node:test | `✖`, `fail 1` | `node --test tests/auth.test.js` |
| Mocha | `1 failing` | `npx mocha tests/auth.spec.js --grep login` |
| RSpec | `Failures:`, `1 example, 1 failure` | `bundle exec rspec spec/auth_spec.rb:42` |
| PHPUnit | `FAILURES!`, `Tests: 3, Failures: 1` | `vendor/bin/phpunit --filter testLogin` |
| Rake / Rails | `Failure:`, `1 failure` | `bin/rails test test/models/auth_test.rb:12` |
| Gradle / Maven | `BUILD FAILED` / `BUILD FAILURE` | `./gradlew test --tests '*AuthTest*'` / `mvn -Dtest=AuthTest test` |

## Was it already red?

Never blame the test before the diff is read. If the test was already red before your edit, say so with evidence: the prior run log, or stash your change and re-run. Without evidence, assume your edit did it.

## Checkpoints

- At `ultra` with `autoRevert: true`, a green→red transition restores files that still match the agent's edit. Conflicts (manual edits) are left alone and reported.
- After an auto-revert, re-run the failing subset before any new edit. A restore is not proof of green.
- `/aftermath-checkpoint status` shows tracked files; `restore` and `clear` are manual overrides.

## Never

- Never patch around a regression with a new guard elsewhere.
- Never widen the change to "make the test pass".
- Never claim green from a partial run; name the command you ran.
