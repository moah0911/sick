# Sick on Windows

## Install

```powershell
git clone https://github.com/moah0911/sick.git sick; cd sick
.\install.ps1            # uv, deps, .env, sick.cmd on PATH, preflight
# or: .\install.ps1 -Global     (uv tool install — sick works from anywhere)
# optional: -WithVideo (Remotion skills), -Uninstall
```

`install.bat` does the same thing from cmd or Explorer. On first run with no
API key, `sick` opens the same setup wizard as on Linux/macOS (provider →
hidden key entry → saved to `.env`).

## Compatibility matrix

| Area | Windows status |
|---|---|
| CLI (`sick`, one-shot tasks, `--learn`, `--preflight`) | Works |
| TUI (Textual), keymap, themes | Works (Textual ships a Windows driver) |
| First-run API-key wizard (`getpass`) | Works |
| File tools, grep/glob, code research, memory, audit | Works (`pathlib`, `portalocker` are cross-platform) |
| Git checkpoints / `/undo` / `/redo` | Works (needs Git for Windows) |
| Templates (`--template`, cookiecutter) | Works |
| LSP server (`sick-lsp`) | Works (file URIs are drive-safe) |
| `sick --sandbox` (bubblewrap) | **Linux only** — `bwrap` has no Windows build; the tool reports this and refuses instead of pretending |
| `bash` tool / `!cmd` | Runs through `cmd.exe`, so use Windows commands (`dir`, `type`). For POSIX commands, run Sick inside WSL — everything works there exactly as on Linux |
| `.env` permissions | Installer restricts via `icacls` (best-effort); keys saved later by the wizard rely on your user profile ACLs |
| Demos | Written for POSIX shells; run under WSL |

## Verifying compatibility

CI runs a `windows-smoke` job (providers, learn, skills + `--version` /
`--list-templates`) on `windows-latest`. The full test suite stays on Linux:
several tests deliberately exercise POSIX behavior (the bash tool's shell
semantics, `.sh` fake editors, symlink escapes) that has no direct Windows
equivalent.

WSL is the recommended setup if you want 100% of Sick (sandbox included):

```powershell
wsl --install
# then, inside WSL: git clone … && ./install.sh
```
