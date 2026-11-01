---
description: commit and push this workspace to GitHub (deterministic flow)
---
Commit this workspace to GitHub. Follow this exact sequence — do not improvise, do not run test suites more than once, and stop with a specific error if a step fails:

1. `bash('gh auth status')` — if it fails, STOP and tell the user to run `gh auth login`. Do not continue.
2. `bash('git status --porcelain; git remote -v')` — see what exists.
3. If there is no `.git` directory: `bash('git init -b main')`.
4. Show the user a one-line summary of what will be committed (files changed count from git status), then `bash('git add -A')`.
5. Commit with a concise message derived from the changes: `bash('git commit -m "<message>"')`. $ARGUMENTS, if given, is the commit message — use it verbatim.
6. If no `origin` remote: `bash('gh repo create --source=. --remote=origin --push')`. Otherwise: `bash('git push -u origin HEAD')`.
7. Reply ONCE with: repo URL (from `git remote get-url origin`), commit short hash, and files committed count. Nothing else.

Never force-push. Never commit `.env` files — if `.env` appears in git status, add it to `.gitignore` first and say so.
