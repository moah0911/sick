# Bundled plugins (vendored, pinned)

Default-on plugins, vendored so Sick works offline and every content
change is a reviewable diff. Refresh deliberately with
`scripts/update_bundled_plugins.py`.

| Plugin | Source | Pin (commit) | License |
|---|---|---|---|
| ponytail | https://github.com/DietrichGebert/ponytail | `96608e078b2d5ea607c5c3b8b5a54d1c1fba6846` | MIT (see `ponytail/LICENSE`) |
| aftermath | https://github.com/moah0911/aftermath | `c6e11fa3e6e7de0f4735dcede334b8940c497965` | MIT (see `aftermath/LICENSE`) |

Vendored: ponytail `skills/*/SKILL.md` (6 skills); aftermath
`AFTERMATH.md`, root `SKILL.md`, `skills/*/SKILL.md` (8 skills).
