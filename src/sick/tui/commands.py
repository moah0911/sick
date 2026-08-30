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


class HelpCommand(SlashCommand):
    name = "help"
    hint = "show this help"

    async def run(self, app: SickApp, args: str) -> str | None:
        lines = ["## commands"]
        for cmd in app.commands.canonical:
            names = " ".join([f"/{cmd.name}"] + [f"/{a}" for a in cmd.aliases])
            lines.append(f"- `{names}` — {cmd.hint}")
        lines.append("\nUse `!cmd` for shell, `@file` to attach, `$ARGUMENTS`/`$1`/`!` `` `cmd` ``/`@file` in custom prompts")
        return "\n".join(lines)


class ClearCommand(SlashCommand):
    name = "clear"
    aliases = ["new"]
    hint = "clear the conversation"

    async def run(self, app: SickApp, args: str) -> str | None:
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
        try:
            from sick.providers import detect

            prov = detect()
            return f"model: `{prov.model_id}` (provider: {prov.name})"
        except Exception:
            pass
        llm = getattr(app.agent, "_llm", None) or getattr(app.agent, "llm", None)
        name = getattr(llm, "model", None) or getattr(llm, "model_id", None) or type(llm).__name__ if llm else "no llm"
        return f"model: `{name}`"


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
        counts = app.agent._tool_counts
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
        return "plan discarded"


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
                content = p.read_text(errors="replace")[:100_000]
                if len(p.read_text(errors="replace")) > 100_000:
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
        return app.agent.checkpoint(args.strip() or "checkpoint")


class RestoreCommand(SlashCommand):
    name = "restore"
    hint = "restore workspace n checkpoints back (/restore [n])"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            n = int(args.strip()) if args.strip() else 1
        except ValueError:
            return "usage: /restore [n]"
        return app.agent.restore(max(1, n))


class CheckpointsCommand(SlashCommand):
    name = "checkpoints"
    hint = "list sick-checkpoints"

    async def run(self, app: SickApp, args: str) -> str | None:
        return app.agent.checkpoints()


class VersionCommand(SlashCommand):
    name = "version"
    hint = "show sick version"

    async def run(self, app: SickApp, args: str) -> str | None:
        try:
            from importlib.metadata import version as _v

            v = _v("sick")
        except Exception:
            v = "0.1.0"
        return f"sick {v}"


class SlashCommandRegistry:
    """Registry of slash commands, dispatchable by name or alias."""

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.commands: dict[str, SlashCommand] = {}
        self.canonical: list[SlashCommand] = []
        for cmd in (
            HelpCommand(), ClearCommand(), ExitCommand(), ModelsCommand(), VisualCommand(),
            AuditCommand(), StatsCommand(), PlanCommand(), ApproveCommand(), RejectCommand(),
            CheckpointCommand(), RestoreCommand(), CheckpointsCommand(), VersionCommand(),
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
