---
name: build-failure
description: >
  Use when compilation, typechecking, bundling, or another build step fails.
  Read the first error, isolate the hunk, and do not run tests until the build
  is green. Distinct from a test regression: the code never ran.
license: MIT
---

# Build Failure

A build failure means the code never reached the tests. Fix the build before interpreting any test result.

## Steps

1. Stop. No new edits until the first error is read.
2. Paste the first error verbatim, with file and line. Later errors are usually noise from the first one.
3. Identify the last edit that touches that file or symbol. Diff it.
4. Fix only that hunk. Do not disable type checks, ignore errors, or loosen compiler flags to get past it.
5. Re-run the same build command. Green build → run the tests. Still red → use the `retry-loop` ladder; do not vary flags blindly.
6. If the build was already red before your edit, say so with evidence instead of claiming you broke it.

## Common signatures

| Tool | Signature |
|------|-----------|
| TypeScript | `error TS2322`, `error TS7006` |
| Rust | `error[E0308]`, `error[E0433]` |
| Go | `cannot use ... as`, `undefined:` |
| Java / Kotlin | `BUILD FAILED`, `compilation failed` |
| Bundlers | `Module not found`, `Failed to compile`, `ELIFECYCLE` |

## Boundaries

- Build failures are advisory in the plugin: they do not freeze forward edits, because fixing the build requires an edit.
- Checkpoint auto-revert applies to green→red tests, not build failures.
- Never "fix" a build by deleting the failing code or suppressing the diagnostic. That is hiding the break.
- If the build fails because a dependency is missing, switch to `dependency-failure`.
