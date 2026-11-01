---
name: dependency-failure
description: >
  Use when an install, lockfile, resolver, or package-manager step fails:
  ERESOLVE, version conflicts, missing distributions, registry or network
  errors. Paste the exact resolver error, respect the lockfile, and change one
  thing at a time.
license: MIT
---

# Dependency Failure

A resolver failure is a fact about the dependency graph, not an invitation to upgrade everything.

## Steps

1. Stop. Do not delete the lockfile or run a broad upgrade.
2. Paste the exact resolver error verbatim. Name the packages and version ranges it mentions.
3. Identify which change introduced the conflict: a new dependency, a bumped range, a Node/Python/Rust version, or a stale lockfile.
4. Choose one deliberate fix:
   - restore the previous version range
   - use the existing lockfile (`npm ci`, `pnpm install --frozen-lockfile`, `yarn install --immutable`, `poetry install`, `cargo fetch`)
   - add the missing peer dependency explicitly
5. Re-run the install command. Then run the build, then the tests.
6. If the install failure is environmental (registry down, auth, network), say so and stop; do not edit manifests to route around it.

## Common signatures

| Ecosystem | Signature |
|-----------|-----------|
| npm | `ERESOLVE`, `npm ERR!`, `ETIMEDOUT`, `ENOTFOUND` |
| Python | `No matching distribution`, `failed to select a version` |
| Rust | `failed to select a version for the requirement` |
| Go | `cannot find module`, `missing go.sum entry` |
| Ruby | `Bundler could not find compatible versions` |
| Lockfiles | `lock file needs to be updated` |

## Never

- Never delete the lockfile as a first move.
- Never loosen a version range without stating why.
- Never mix a dependency fix with feature changes.
- Never label a registry outage as a code bug.
