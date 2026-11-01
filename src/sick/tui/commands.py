from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sick.tui.app import SickApp


class SlashCommand:
    """A `/name` command. `run` returns chat lines, or None for silent."""

    name: str = ""
    aliases: list[str] = []
    hint: str = ""

    async def run(self, app: SickApp, args: str) -> str | None:
        return None


_HELP_GROUPS: list[tuple[str, list[str]]] = [
    ("session", ["clear", "sessions", "compact", "export", "undo", "redo"]),
    ("work", ["plan", "approve", "reject", "run", "visual", "learn"]),
    ("plugins", ["ponytail", "ponytail-review", "ponytail-audit", "ponytail-debt", "ponytail-help", "aftermath", "aftermath-status", "aftermath-revert", "aftermath-log", "aftermath-audit"]),
    ("git & history", ["checkpoint", "restore", "checkpoints", "audit", "stats"]),
    ("view & setup", ["status", "models", "skills", "details", "thinking", "themes", "connect", "editor", "init", "update", "version", "help", "exit"]),
]

_KEYMAP = """## keys (ctrl+x leader)
`ctrl+x h` help · `ctrl+x n` new · `ctrl+x c` compact · `ctrl+x l` learn · `ctrl+x s` sessions
`ctrl+x u` undo · `ctrl+x r` redo · `ctrl+x e` editor · `ctrl+x x` export · `ctrl+x m` models
`ctrl+x t` themes · `ctrl+t` next theme · `ctrl+x d` details · `ctrl+x q` quit · `ctrl+c` interrupt
`ctrl+l` clear · `f1` help · `esc`/`ctrl+x space` focus input · `↑`/`↓` history · `pgup`/`pgdn` scroll"""


class HelpCommand(SlashCommand):
    name = "help"
    hint = "show this help"

    async def run(self, app: SickApp, args: str) -> str | None:
        by_name = {c.name: c for c in app.commands.canonical}
        grouped: set[str] = set()
        lines = ["## commands"]
        for title, names in _HELP_GROUPS:
            members = [by_name[n] for n in names if n in by_name]
            if not members:
                continue
            lines.append(f"\n### {title}")
            for cmd in members:
                grouped.add(cmd.name)
                aliases = " ".join(f"/{a}" for a in cmd.aliases)
                lines.append(f"- `/{cmd.name}`{f' {aliases}' if aliases else ''} — {cmd.hint}")
        custom = [c for c in app.commands.canonical if c.name not in grouped]
        if custom:
            lines.append("\n### custom")
            for cmd in custom:
                lines.append(f"- `/{cmd.name}` — {cmd.hint}")
        lines.append(f"\n{_KEYMAP}")
        lines.append("\nUse `!cmd` for shell, `@file` to attach; custom prompts support `$ARGUMENTS`/`$1`/`` !`cmd` ``/`@file`")
        return "\n".join(lines)


class ClearCommand(SlashCommand):
    name = "clear"
    aliases = ["new"]
    hint = "clear the conversation"

    async def run(self, app: SickApp, args: str) -> str | None:
        if app.chat_view:
            app.chat_view.clear()
        app.agent.context["user_request"] = ""
        return "conversation cleared"


class ExitCommand(SlashCommand):
    name = "exit"
    aliases = ["quit", "q"]
    hint = "quit sick"

    async def run(self, app: SickApp, args: str) -> str | None:
        app.exit()
        return None


class ModelsCommand(SlashCommand):
    name = "models"
    hint = "show the active model/provider"

    async def run(self, app: SickApp, args: str) -> str | None:
        from sick.providers import client_model_name

        live = client_model_name(app.agent)
        if live:
            try:
                from sick.providers import detect

                return f"model: `{live}` (provider: {detect().name}, live client)"
            except Exception:
                return f"model: `{live}` (live client)"
        try:
            from sick.providers import detect

            prov = detect()
            return f"model: `{prov.model_id}` (provider: {prov.name})"
        except Exception:
            return "model: `no llm`"


class AuditCommand(SlashCommand):
    name = "audit"
    hint = "show the last N tool calls (/audit [n])"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            n = int(args) if args.strip() else 10
        except ValueError:
            return "usage: /audit [n]"
        entries = app.agent.audit.entries(max(1, min(n, 100)))
        if not entries:
            return "no tool calls recorded yet"
        lines = []
        for e in entries:
            ok = "ok" if e["ok"] else "FAILED"
            arg_str = ", ".join(f"{k}={str(v)[:60]}" for k, v in (e.get("args") or {}).items())
            if arg_str:
                lines.append(f"- [{ok}] {e['tool']} ({e['duration_ms']}ms) {arg_str}")
            else:
                lines.append(f"- [{ok}] {e['tool']} ({e['duration_ms']}ms)")
        return "\n".join(lines)


class StatsCommand(SlashCommand):
    name = "stats"
    hint = "show turn and tool-call counts for this session"

    async def run(self, app: SickApp, args: str) -> str | None:
        counts = app.agent.registry.counts() if hasattr(app.agent, 'registry') else {}
        lines = [f"turns: {app.agent.turns}"]
        if counts:
            total = sum(counts.values())
            lines.append(f"tool calls: {total}")
            for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
                lines.append(f"  {name}: {count}")
        else:
            lines.append("tool calls: none yet")
        return "\n".join(lines)


class PlanCommand(SlashCommand):
    name = "plan"
    hint = "ask the agent for a plan without executing (/plan <task>)"

    async def run(self, app: SickApp, args: str) -> str | None:
        if not args.strip():
            return "usage: /plan <task or description>"
        app.pending_task = args
        try:
            run = app.agent.begin_run(args, planned=True)
            app.agent.context["sdlc_state"] = app.agent.lifecycle.prompt(run)
        except Exception:
            pass
        await app._send(
            f"Produce a plan for this task (no execution yet): {args}\n"
            "List the steps, files to touch, and how you will verify. "
            "The user will approve with /approve or revise with /reject.",
            show=False,
        )
        return f"planned: {args} — approve with `/approve`"


class ApproveCommand(SlashCommand):
    name = "approve"
    hint = "execute the pending /plan task"

    async def run(self, app: SickApp, args: str) -> str | None:
        if not app.pending_task:
            return "nothing pending — start with `/plan <task>`"
        task = app.pending_task
        app.pending_task = None
        try:
            if getattr(app.agent, "current_run", None) is not None:
                app.agent.lifecycle.approve(app.agent.current_run)
        except Exception:
            pass
        await app._send(
            f"Execute the plan you produced for: {task}",
            show=False,
        )
        return f"executing: {task}"


class RejectCommand(SlashCommand):
    name = "reject"
    hint = "discard the pending /plan task"

    async def run(self, app: SickApp, args: str) -> str | None:
        if not app.pending_task:
            return "nothing pending"
        app.pending_task = None
        try:
            if getattr(app.agent, "current_run", None) is not None:
                app.agent.lifecycle.cancel(app.agent.current_run)
        except Exception:
            pass
        return "plan discarded"


class RunCommand(SlashCommand):
    name = "run"
    hint = "show the current SDLC run: phase, tier, gate (/run)"

    async def run(self, app: SickApp, args: str) -> str | None:
        run = getattr(app.agent, "current_run", None)
        if run is None:
            return "no SDLC run yet — send a task or start with `/plan <task>`"
        verdict = app.agent.lifecycle.can_deliver(run)
        gate = "DELIVERABLE" if verdict.allowed else "BLOCKED: " + "; ".join(verdict.reasons)
        files = ", ".join(run.changed_files) or "none"
        return (
            f"run `{run.id}` · phase `{run.phase.value}` · tier `{run.tier.value}`\n"
            f"gate: {gate}\nchanged: {files}\nskills: {run.skills or 'none'}\nartifacts: `{run.dir}`"
        )


class VisualCommand(SlashCommand):
    name = "visual"
    hint = "make an explanatory video with Remotion (/visual <topic>)"

    async def run(self, app: SickApp, args: str) -> str | None:
        if not args.strip():
            return "usage: /visual <topic or description>"
        await app._send(
            f"Create an explanatory visualization video about: {args}\n"
            "Follow the remotion skill (always active). Scaffold the Remotion "
            "project inside the workspace, design a video-first composition, "
            "render it with `npx remotion render`, and report the final video path.",
            show=False,
        )
        return f"making a video about: {args}"


def _expand_template(template: str, args: str, workspace: Path, agent=None) -> str:
    """Expand $ARGUMENTS, $1..$9, !`shell`, @file — opencode compatible, order args→shell→file."""
    # 1. args
    try:
        tokens = shlex.split(args, posix=True) if args.strip() else []
    except ValueError:
        tokens = args.split()
    out = template
    # preserve $ARGUMENTS placeholder first
    out = out.replace("$ARGUMENTS", "__ARG__").replace("{{args}}", "__ARG__").replace("$ARGS", "__ARG__")
    # $1..$9
    def _repl_num(m):
        idx = int(m.group(1))
        return tokens[idx - 1] if 0 < idx <= len(tokens) else ""

    out = re.sub(r"\$([1-9])", _repl_num, out)
    out = out.replace("__ARG__", args)
    # 2. shell !`cmd`
    def _shell(m):
        cmd = m.group(1).strip()
        if not cmd:
            return ""
        try:
            # reuse workspace cwd, timeout 10, bounded 20k
            r = subprocess.run(cmd, shell=True, cwd=workspace, capture_output=True, text=True, timeout=10)
            txt = (r.stdout + (("\n" + r.stderr) if r.stderr else "")).strip()[:20000] or "(no output)"
            if r.returncode != 0:
                txt += f"\n[exit code {r.returncode}]"
            return txt
        except subprocess.TimeoutExpired:
            return "[timed out after 10s]"
        except Exception as e:
            return f"[error: {e}]"

    out = re.sub(r"!`([^`]+)`", _shell, out)
    # 3. file @path — reuse attach logic but inline
    # dedupe, total cap 300k, per file 100k
    seen: set[str] = set()
    total = 0
    # collect matches before mutating out to avoid re-scanning injected content
    matches = list(re.finditer(r"(?<!\w)@([^\s,;`]+)", out))
    # also quoted @"..."
    matches += list(re.finditer(r'@\"([^\"]+)\"', out))
    for m in matches:
        raw = m.group(1).strip().rstrip(",.;: )]`'\"")
        if not raw or raw in seen:
            continue
        seen.add(raw)
        if total > 300_000:
            out += f"\n[skipped @ {raw}: total cap reached]"
            continue
        try:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = (workspace / p).resolve()
            else:
                p = p.resolve()
            if not p.exists() or p.is_dir():
                out = out.replace(f"@{raw}", f"[attach missing: {raw}]")
                continue
            if p.suffix.lower() == ".pdf" and agent:
                try:
                    content = agent.parse_pdf(str(p))
                except Exception as e:
                    content = f"[unreadable: {e}]"
            else:
                raw_text = p.read_text(errors="replace")
                content = raw_text[:100_000]
                if len(raw_text) > 100_000:
                    content += "\n[truncated after 100000 bytes]"
            # avoid re-injecting shell/file in content
            total += len(content)
            out = out.replace(f"@{raw}", f"\n--- attached: {p} ---\n{content}")
            # also replace quoted form
            out = out.replace(f'@\"{raw}\"', f"\n--- attached: {p} ---\n{content}")
        except Exception as e:
            out = out.replace(f"@{raw}", f"[unreadable: {e}]")
    return out


class PromptCommand(SlashCommand):
    """User-defined prompt from .sick/commands/*.md or opencode.json — opencode compat."""

    def __init__(self, name: str, hint: str, template: str, agent: str = "", subtask: bool = False, model: str = ""):
        self.name = name
        self.hint = hint or name
        self.template = template
        self.agent_hint = agent
        self.subtask = subtask
        self.model = model

    async def run(self, app: SickApp, args: str) -> str | None:
        ws = Path(getattr(app.agent, "workspace", Path.cwd()))
        prompt = _expand_template(self.template, args, ws, app.agent)
        if not prompt.strip():
            return "prompt is empty"
        # model override
        prev = None
        if self.model:
            try:
                from sick.providers import detect

                prev = getattr(app.agent, "_llm", None)
                # try create, but don't crash if key missing
                try:
                    app.agent._llm = detect(self.model).create_llm()
                    app.agent.context["model_override"] = self.model
                except Exception as e:
                    prompt = f"[model {self.model} unavailable: {e}]\n{prompt}"
            except Exception:
                pass
        if self.agent_hint:
            prompt = f"[agent: {self.agent_hint}]\n{prompt}"
        # subtask = no user bubble
        if self.subtask:
            await app.host.submit(prompt)
            if prev is not None:
                try:
                    app.agent._llm = prev
                except Exception:
                    pass
            return f"[{self.name} subtask started]"
        await app._send(prompt, show=True)
        if prev is not None:
            try:
                app.agent._llm = prev
                app.agent.context.pop("model_override", None)
            except Exception:
                pass
        return None


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """Parse --- frontmatter, return (meta, body). Naive but handles opencode keys."""
    if not raw.startswith("---"):
        return {}, raw.strip()
    try:
        parts = raw.split("---", 2)
        if len(parts) < 3:
            return {}, raw.strip()
        _, fm, rest = parts
        meta: dict = {}
        # try yaml if available
        try:
            import yaml  # type: ignore

            loaded = yaml.safe_load(fm)
            if isinstance(loaded, dict):
                meta = {k.lower(): v for k, v in loaded.items()}
        except Exception:
            # fallback naive k: v
            for line in fm.splitlines():
                line = line.strip()
                if not line or ":" not in line or line.startswith("#"):
                    continue
                k, v = line.split(":", 1)
                k = k.strip().lower()
                v = v.strip().strip('"').strip("'")
                if k in {"description", "agent", "model", "subtask", "template"}:
                    meta[k] = v
        body = rest.strip()
        # allow template key in frontmatter as alias
        if "template" in meta and not body:
            body = str(meta.pop("template"))
        # coerce subtask bool
        if "subtask" in meta:
            v = meta["subtask"]
            if isinstance(v, str):
                meta["subtask"] = v.lower() in {"1", "true", "yes", "on"}
            else:
                meta["subtask"] = bool(v)
        return meta, body
    except Exception:
        return {}, raw.strip()


def _load_json_commands(workspace: Path) -> list[PromptCommand]:
    cmds: list[PromptCommand] = []
    candidates = [
        Path.home() / ".config" / "opencode" / "opencode.json",
        Path.home() / ".sick" / "opencode.json",
        workspace / "opencode.json",
        workspace / ".sick" / "opencode.json",
        workspace / "sick.json",
        workspace / ".opencode" / "opencode.json",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text())
            block = data.get("command", {})
            if not isinstance(block, dict):
                continue
            for name, cfg in block.items():
                if not isinstance(cfg, dict):
                    continue
                template = cfg.get("template", "")
                if not template or not isinstance(template, str):
                    continue
                cmds.append(
                    PromptCommand(
                        name=str(name),
                        hint=str(cfg.get("description", name)),
                        template=str(template),
                        agent=str(cfg.get("agent", "")),
                        subtask=bool(cfg.get("subtask", False)),
                        model=str(cfg.get("model", "")),
                    )
                )
        except Exception:
            continue
    # also check SickConfig.command from .sick/config.toml
    try:
        from sick.config import load_config

        cfg = load_config(workspace)
        for name, c in (cfg.get("command") or {}).items():
            if isinstance(c, dict) and c.get("template"):
                cmds.append(
                    PromptCommand(
                        name=str(name),
                        hint=str(c.get("description", name)),
                        template=str(c["template"]),
                        agent=str(c.get("agent", "")),
                        subtask=bool(c.get("subtask", False)),
                        model=str(c.get("model", "")),
                    )
                )
            elif isinstance(c, str):
                cmds.append(PromptCommand(str(name), str(name), str(c)))
    except Exception:
        pass
    return cmds


def _load_prompt_commands(workspace) -> list[SlashCommand]:
    cmds: list[SlashCommand] = []
    # 4 md dirs in precedence low→high
    search_dirs = [
        Path.home() / ".config" / "opencode" / "commands",
        Path.home() / ".sick" / "commands",
        Path(workspace) / ".opencode" / "commands" if workspace else None,
        Path(workspace) / ".sick" / "commands" if workspace else None,
    ]
    # first load JSON (lower precedence than md)
    for pc in _load_json_commands(Path(workspace) if workspace else Path.cwd()):
        cmds.append(pc)
    for base in search_dirs:
        if not base or not base.is_dir():
            continue
        for p in sorted(base.glob("*.md")):
            try:
                raw = p.read_text(errors="replace")
            except OSError:
                continue
            meta, body = _parse_frontmatter(raw)
            if not body:
                continue
            hint = str(meta.get("description", p.stem))
            # allow override of builtins (opencode does)
            cmds.append(
                PromptCommand(
                    p.stem,
                    hint or p.stem,
                    body,
                    agent=str(meta.get("agent", "")),
                    subtask=bool(meta.get("subtask", False)),
                    model=str(meta.get("model", "")),
                )
            )
    return cmds


class CheckpointCommand(SlashCommand):
    name = "checkpoint"
    hint = "snapshot workspace to sick-checkpoints branch"

    async def run(self, app: SickApp, args: str) -> str | None:
        return str(app.agent.checkpoint(args.strip() or "checkpoint"))


class RestoreCommand(SlashCommand):
    name = "restore"
    hint = "restore workspace n checkpoints back (/restore [n])"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            n = int(args.strip()) if args.strip() else 1
        except ValueError:
            return "usage: /restore [n]"
        return str(app.agent.restore(max(1, n)))


class CheckpointsCommand(SlashCommand):
    name = "checkpoints"
    hint = "list sick-checkpoints"

    async def run(self, app: SickApp, args: str) -> str | None:
        return str(app.agent.checkpoints())


class VersionCommand(SlashCommand):
    name = "version"
    hint = "show sick version"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            from importlib.metadata import version as _v

            v = _v("sick-agent")
        except Exception:
            v = "0.5.0"
        return f"sick {v}"


class LearnCommand(SlashCommand):
    name = "learn"
    hint = "learn from this session and improve sick itself (/learn [focus])"

    async def run(self, app: SickApp, args: str) -> str | None:
        from sick.learn import build_learn_prompt

        focus = args.strip()
        brief = str(app.agent.learn_brief(focus))
        await app._send(build_learn_prompt(brief, focus), show=False)
        return brief + "\n\nself-improvement started — rollback anytime with `/restore`"


class UndoCommand(SlashCommand):
    name = "undo"
    hint = "undo the last change set (back to the previous checkpoint)"

    async def run(self, app: SickApp, args: str) -> str | None:
        # snapshot current state first so /redo can return to it
        snap = app.agent.checkpoint("before-undo")
        created = snap.startswith("checkpoint created")
        out = str(app.agent.restore(2 if created else 1))
        if out.startswith("[error"):
            return out if "no checkpoints" in out else f"{out} — nothing to undo"
        app._can_redo = created
        return f"undid last change set ({out})" + (" — `/redo` to bring it back" if created else "")


class RedoCommand(SlashCommand):
    name = "redo"
    hint = "redo a change set undone with /undo"

    async def run(self, app: SickApp, args: str) -> str | None:
        if not getattr(app, "_can_redo", False):
            return "nothing to redo — use `/undo` first"
        out = str(app.agent.restore(1))
        if out.startswith("[error"):
            return out
        app._can_redo = False
        return f"redone ({out})"


class CompactCommand(SlashCommand):
    name = "compact"
    aliases = ["summarize"]
    hint = "compact the session into a summary and clear the chat"

    async def run(self, app: SickApp, args: str) -> str | None:
        from sick.learn import analyze_audit, summarize

        report = analyze_audit(app.agent.audit.entries(50), turns=app.agent.turns)
        summary = summarize(report, app.agent.memory.recall(""))
        app.agent.context["compact_summary"] = summary
        app.transcript = [("sick", f"[compacted session]\n{summary}")]
        if app.chat_view:
            app.chat_view.clear()
        return f"session compacted — summary kept in context:\n{summary}"


class ExportCommand(SlashCommand):
    name = "export"
    hint = "export the conversation to Markdown (/export [path])"

    async def run(self, app: SickApp, args: str) -> str | None:
        import time

        ws = Path(getattr(app.agent, "workspace", Path.cwd()))
        if args.strip():
            dest = Path(args.strip()).expanduser()
            if not dest.is_absolute():
                dest = ws / dest
        else:
            dest = ws / ".sick" / "exports" / f"session-{time.strftime('%Y%m%d-%H%M%S')}.md"
        lines = [f"# sick session — {ws}", ""]
        for role, text in getattr(app, "transcript", []):
            lines.append(f"## {role}\n\n{text}\n")
        if not getattr(app, "transcript", []):
            counts = app.agent.registry.counts() if hasattr(app.agent, 'registry') else {}
            stats = ", ".join(f"{k}×{v}" for k, v in sorted(counts.items())) or "no tool calls yet"
            lines.append(f"## session\n\nturns: {app.agent.turns} · tools: {stats}\n")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("\n".join(lines))
        except OSError as e:
            return f"[error: export failed: {e}]"
        return f"exported conversation → {dest}"


class InitCommand(SlashCommand):
    name = "init"
    hint = "create AGENTS.md + .sick/config.toml for this workspace"

    async def run(self, app: SickApp, args: str) -> str | None:
        ws = Path(getattr(app.agent, "workspace", Path.cwd()))
        agents_md = ws / "AGENTS.md"
        if agents_md.exists():
            return "AGENTS.md already exists — leaving it untouched (edit it directly)"
        top = sorted(p.name for p in ws.iterdir() if not p.name.startswith("."))[:20] if ws.is_dir() else []
        cmds = ", ".join(f"/{c.name}" for c in app.commands.canonical[:12])
        body = (
            f"# {ws.name}\n\n"
            "Project guide for AI coding agents (sick `/init`).\n\n"
            f"Top-level: {', '.join(top) or '(empty)'}\n\n"
            "## Working agreements\n\n"
            "- Shortest correct change; verify with tests after every change.\n"
            "- sick checkpoints live on the `sick-checkpoints` branch (`/restore` to undo).\n"
            f"- Useful commands: {cmds}\n"
        )
        out = app.agent.write_file("AGENTS.md", body)
        if out.startswith("Error"):
            return f"[error: {out}]"
        cfg = ws / ".sick" / "config.toml"
        if not cfg.exists():
            try:
                cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg.write_text('# model = "gpt-4o-mini"\n# excluded = ["vendor"]\n')
            except OSError:
                pass
        return "created AGENTS.md (+ .sick/config.toml) — edit it to teach agents this project"


class SessionsCommand(SlashCommand):
    name = "sessions"
    aliases = ["resume", "continue"]
    hint = "list checkpoints + recent sessions (restore with /restore [n])"

    async def run(self, app: SickApp, args: str) -> str | None:
        lines = ["## sessions"]
        cps = app.agent.checkpoints()
        lines.append("checkpoints (newest first):")
        lines.append(cps if not cps.startswith("[error") else "  (none yet — /checkpoint to create one)")
        recent = app.agent.memory.recall("", top_k=5)
        if recent:
            lines.append("recent experience:")
            lines += [f"- {e.task}: {e.outcome}" for e in recent]
        lines.append(f"this session: {app.agent.turns} turns · restore with `/restore [n]`")
        return "\n".join(lines)


def _persist_plugin_mode(app: SickApp, key: str, value: str) -> None:
    try:
        cfg_dir = Path(getattr(app.agent, "workspace", ".")) / ".sick"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg = cfg_dir / "config.toml"
        lines = cfg.read_text().splitlines() if cfg.exists() else []
        lines = [ln for ln in lines if not ln.strip().startswith(f"{key} =")]
        lines.append(f'{key} = "{value}"')
        cfg.write_text("\n".join(lines) + "\n")
    except Exception:
        pass


class PonytailCommand(SlashCommand):
    name = "ponytail"
    hint = "ponytail level: /ponytail [lite|full|ultra|off]"

    async def run(self, app: SickApp, args: str) -> str | None:
        want = args.strip().lower()
        if not want:
            return f"ponytail: {getattr(app.agent, 'ponytail_mode', 'full')} (real bundled skill, see /ponytail-help)"
        out = str(app.agent.set_ponytail_mode(want))
        if "unknown" not in out:
            _persist_plugin_mode(app, "ponytail", want)
        return out


class PonytailReviewCommand(SlashCommand):
    name = "ponytail-review"
    hint = "review the current diff like the senior dev who gets paged"

    async def run(self, app: SickApp, args: str) -> str | None:
        target = args.strip() or "uncommitted"
        await app._send(
            f"Load the bundled skill with load_skill('ponytail-review') and review the {target} diff "
            "following it exactly: bugs, security, real load, risky code without tests, slow paths, what to cut.",
            show=False,
        )
        return f"ponytail review started ({target})"


class PonytailAuditCommand(SlashCommand):
    name = "ponytail-audit"
    hint = "audit the whole repo, most important first"

    async def run(self, app: SickApp, args: str) -> str | None:
        await app._send(
            "Load the bundled skill with load_skill('ponytail-audit') and audit this whole repo "
            "following it exactly. Rank findings, most important first.",
            show=False,
        )
        return "ponytail audit started"


class PonytailDebtCommand(SlashCommand):
    name = "ponytail-debt"
    hint = "harvest shortcut: comments into a ledger"

    async def run(self, app: SickApp, args: str) -> str | None:
        hits = app.agent.grep(r"shortcut:")
        if not hits or (hits and hits[0].startswith("Error:")):
            return "ponytail debt: no `shortcut:` comments found"
        lines = [f"## ponytail debt ({len(hits)})"] + [f"- {h}" for h in hits[:30]]
        return "\n".join(lines)


class PonytailHelpCommand(SlashCommand):
    name = "ponytail-help"
    hint = "ponytail quick reference (bundled skill)"

    async def run(self, app: SickApp, args: str) -> str | None:
        from sick.plugins import ponytail_skill_body

        return ponytail_skill_body("ponytail-help")[:6000] or "ponytail help unavailable (bundled files missing)"


class AftermathCommand(SlashCommand):
    name = "aftermath"
    hint = "aftermath recovery level: /aftermath [lite|full|ultra|off]"

    async def run(self, app: SickApp, args: str) -> str | None:
        want = args.strip().lower()
        if not want:
            return str(app.agent.aftermath_status())
        out = str(app.agent.set_aftermath_mode(want))
        if "unknown" not in out:
            _persist_plugin_mode(app, "aftermath", want)
        return out


class AftermathStatusCommand(SlashCommand):
    name = "aftermath-status"
    hint = "what changed / failure + guard state"

    async def run(self, app: SickApp, args: str) -> str | None:
        return str(app.agent.aftermath_status())


class AftermathRevertCommand(SlashCommand):
    name = "aftermath-revert"
    hint = "undo the last change set via checkpoint restore"

    async def run(self, app: SickApp, args: str) -> str | None:
        out = str(app.agent.restore(1))
        if "restored" in out:
            app.agent.guard.frozen = False
        return out


class AftermathLogCommand(SlashCommand):
    name = "aftermath-log"
    hint = "append a one-line postmortem to AFTERMATH.log"

    async def run(self, app: SickApp, args: str) -> str | None:
        import time

        text = args.strip() or "postmortem"
        path = Path(getattr(app.agent, "workspace", ".")) / "AFTERMATH.log"
        with path.open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M')} {text}\n")
        return f"logged to {path.name}"


class AftermathAuditCommand(SlashCommand):
    name = "aftermath-audit"
    hint = "scan the diff for scope creep (bundled aftermath skill)"

    async def run(self, app: SickApp, args: str) -> str | None:
        await app._send(
            "Load the bundled skill with load_skill('aftermath') and scan the current diff for "
            "scope creep following it exactly. Report only what the evidence shows.",
            show=False,
        )
        return "aftermath audit started"


class StatusCommand(SlashCommand):
    name = "status"
    hint = "full session status (workspace, model, SDLC, plugins)"

    async def run(self, app: SickApp, args: str) -> str | None:
        lines = app.status_lines() if hasattr(app, "status_lines") else ["## status", "unavailable"]
        return "\n".join(lines)


class SkillsCommand(SlashCommand):
    name = "skills"
    hint = "list discovered skills by source + what this run routed"

    async def run(self, app: SickApp, args: str) -> str | None:
        from pathlib import Path

        discovered = getattr(app.agent, "discovered_skills", []) or []
        if not discovered:
            return "no skills discovered — install SKILL.md under ~/.agents/skills, ~/.sick/skills, or .sick/skills"
        ws = Path(getattr(app.agent, "workspace", ".")).resolve()
        home = Path.home()
        groups: dict[str, list] = {"bundled": [], "workspace": [], "user": [], "host": []}
        for s in discovered:
            p = Path(s.path)
            if "bundled" in p.parts:
                groups["bundled"].append(s)
            elif ws in p.parents and ".sick" in p.parts:
                groups["workspace"].append(s)
            elif home / ".sick" in p.parents:
                groups["user"].append(s)
            else:
                groups["host"].append(s)
        lines = ["## skills"]
        for label in ("bundled", "workspace", "user", "host"):
            items = groups[label]
            if items:
                lines.append(f"### {label} ({len(items)})")
                lines += [f"- **{s.name}** — {s.description}" for s in items[:15]]
                if len(items) > 15:
                    lines.append(f"- …and {len(items) - 15} more")
        run = getattr(app.agent, "current_run", None)
        if run is not None and run.skills:
            lines.append("### routed this run")
            lines += [f"- {phase}: `{name}`" for phase, name in run.skills.items()]
        lines.append("load any skill in chat via the agent, e.g. ask it to `load_skill(name)`")
        return "\n".join(lines)


class DetailsCommand(SlashCommand):
    name = "details"
    hint = "toggle verbose tool output"

    async def run(self, app: SickApp, args: str) -> str | None:
        app.show_details = not getattr(app, "show_details", False)
        app.agent.context["details"] = "on" if app.show_details else "off"
        return f"tool details: {'on (full output)' if app.show_details else 'off (truncated)'}"


class ThinkingCommand(SlashCommand):
    name = "thinking"
    hint = "toggle visibility of reasoning blocks"

    async def run(self, app: SickApp, args: str) -> str | None:
        app.show_thinking = not getattr(app, "show_thinking", False)
        app.agent.context["thinking"] = "visible" if app.show_thinking else "hidden"
        return f"thinking blocks: {'visible' if app.show_thinking else 'hidden'}"


class EditorCommand(SlashCommand):
    name = "editor"
    hint = "compose a message in $EDITOR"

    async def run(self, app: SickApp, args: str) -> str | None:
        import os
        import tempfile

        editor = os.environ.get("EDITOR", "").strip()
        if not editor:
            return "EDITOR is not set — e.g. `export EDITOR=vim` or `export EDITOR='code --wait'`"
        fd, tmp = tempfile.mkstemp(suffix=".md", prefix="sick-msg-")
        os.close(fd)
        try:
            # shlex posix mode eats Windows path backslashes (C:\...)
            if os.name == "nt":
                argv = [p.strip('"') for p in shlex.split(editor, posix=False)] + [tmp]
            else:
                argv = shlex.split(editor) + [tmp]
            try:
                with app.suspend():
                    subprocess.run(argv, check=False)
            except Exception:
                subprocess.run(argv, check=False)
            content = Path(tmp).read_text(errors="replace").strip()
        except OSError as e:
            return f"[error: editor failed: {e}]"
        finally:
            Path(tmp).unlink(missing_ok=True)
        if not content:
            return "editor closed with no content — nothing sent"
        await app._send(content)
        return "sent message composed in editor"


class ConnectCommand(SlashCommand):
    name = "connect"
    hint = "provider status, or switch live: /connect groq|meta|openai|nvidia|anthropic"

    async def run(self, app: SickApp, args: str) -> str | None:
        import os

        from sick.providers import PROVIDER_KEYS

        want = args.strip().lower()
        if want == "setup":
            return "to add or change a key, exit and run `sick --setup` (hidden input — keys are never entered in chat, where they'd land in the transcript)"
        if want:
            if want not in PROVIDER_KEYS:
                return f"unknown provider `{want}` — choose: {', '.join(PROVIDER_KEYS)}, or `/connect setup`"
            switch = getattr(app.agent, "switch_provider", None)
            if switch is None:
                return "this agent cannot switch providers live — restart sick after editing `.env`"
            return str(switch(want))
        lines = ["## providers"]
        for provider, var in PROVIDER_KEYS.items():
            lines.append(f"- {var} ({provider}): {'set' if os.environ.get(var) else 'not set'}")
        try:
            from sick.providers import detect

            prov = detect()
            base = getattr(prov, "base_url", None)
            lines.append(f"active: `{prov.model_id}` via {prov.name}" + (f" ({base})" if base else ""))
        except Exception as e:
            lines.append(f"active: none ({e})")
        if os.environ.get("SICK_BASE_URL"):
            lines.append(f"SICK_BASE_URL: {os.environ['SICK_BASE_URL']}")
        lines.append("switch live with `/connect <provider>` (key must already be saved); add/change keys with `sick --setup`")
        return "\n".join(lines)


class ThemesCommand(SlashCommand):
    name = "themes"
    hint = "list themes, or switch with /themes <name>"

    async def run(self, app: SickApp, args: str) -> str | None:
        names = sorted(app.available_themes)
        want = args.strip()
        if want:
            if want not in app.available_themes:
                return f"unknown theme `{want}` — available: {', '.join(names)}"
            app.theme = want
            return f"theme → {want}"
        return f"theme: {app.theme}\navailable: {', '.join(names)}\nswitch with `/themes <name>`"


class UpdateCommand(SlashCommand):
    name = "update"
    hint = "show version and how to update sick"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            from importlib.metadata import version as _v

            v = _v("sick-agent")
        except Exception:
            v = "0.5.0"
        return (
            f"sick {v}\n"
            "update (checkout): `git pull && ./install.sh`\n"
            "update (global): `./install.sh --global`\n"
            "sick never updates itself without being asked"
        )


class SlashCommandRegistry:
    """Registry of slash commands, dispatchable by name or alias."""

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.commands: dict[str, SlashCommand] = {}
        self.canonical: list[SlashCommand] = []
        for cmd in (
            HelpCommand(), ClearCommand(), ExitCommand(), ModelsCommand(), VisualCommand(),
            AuditCommand(), StatsCommand(), PlanCommand(), ApproveCommand(), RejectCommand(), RunCommand(),
            CheckpointCommand(), RestoreCommand(), CheckpointsCommand(), VersionCommand(),
            LearnCommand(), UndoCommand(), RedoCommand(), CompactCommand(), ExportCommand(),
            InitCommand(), SessionsCommand(), StatusCommand(), SkillsCommand(), DetailsCommand(), ThinkingCommand(),
            EditorCommand(), ConnectCommand(), ThemesCommand(), UpdateCommand(), PonytailCommand(), PonytailReviewCommand(), PonytailAuditCommand(), PonytailDebtCommand(), PonytailHelpCommand(), AftermathCommand(), AftermathStatusCommand(), AftermathRevertCommand(), AftermathLogCommand(), AftermathAuditCommand(),
        ):
            self.commands[cmd.name] = cmd
            self.canonical.append(cmd)
            for alias in cmd.aliases:
                self.commands[alias] = cmd
        # custom prompt commands — allow override of builtins (opencode parity)
        try:
            ws = Path(workspace) if workspace else Path.cwd()
            for pc in _load_prompt_commands(ws):
                if pc.name in self.commands:
                    # replace canonical entry
                    old = self.commands[pc.name]
                    if old in self.canonical:
                        self.canonical.remove(old)
                self.commands[pc.name] = pc
                self.canonical.append(pc)
                # also register aliases? prompt commands have no aliases
        except Exception:
            pass

    async def dispatch(self, app: SickApp, line: str) -> str | None:
        parts = line[1:].strip().split(maxsplit=1)
        if not parts or not parts[0]:
            return "unknown command — try `/help`"
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        cmd = self.commands.get(name)
        if not cmd:
            try:
                import difflib

                sug = difflib.get_close_matches(name, self.commands.keys(), n=1, cutoff=0.6)
                if sug:
                    return f"unknown command `/{name}` — did you mean `/{sug[0]}`? try `/help`"
            except Exception:
                pass
            return f"unknown command `/{name}` — try `/help`"
        try:
            return await cmd.run(app, args)
        except Exception as e:
            return f"[error: {e}]"
