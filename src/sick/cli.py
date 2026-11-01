import argparse
import asyncio
import os
import sys
from pathlib import Path

from nooa import CodeActStrategy, set_default_strategy
from nooa.config import CodeActConfig

from sick import SickAgent, detect
from sick.config import load_config
from sick.logging_conf import configure_logging
from sick.preflight import preflight

try:
    from importlib.metadata import version as _pkg_version

    try:
        __version__ = _pkg_version("sick-agent")
    except Exception:
        __version__ = _pkg_version("sick")
except Exception:
    __version__ = "0.2.5"


def main() -> None:
    parser = argparse.ArgumentParser(prog="sick", description="Self-improving coding agent")
    parser.add_argument("task", nargs="?", help="Task to perform")
    parser.add_argument("--modify", help="Self-modification instruction")
    parser.add_argument("--learn", nargs="?", const="", default=None, help="Learn from the session and improve sick itself [focus]")
    parser.add_argument("--attach", action="append", default=[], help="Attach a file (PDF parsed via Docling)")
    parser.add_argument("--workspace", default=None, help="Project directory to work in (default: .)")
    parser.add_argument("--model", default=None, help="Override the LLM model")
    parser.add_argument("--max-iterations", type=int, default=25, help="CodeAct max iterations")
    parser.add_argument("--sandbox", action="store_true", help="Run bash inside a bwrap sandbox (beta)")
    parser.add_argument("--preflight", action="store_true", help="Run health checks and exit")
    parser.add_argument("--setup", action="store_true", help="Configure/change the LLM provider + API key (hidden input), then start")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--template", choices=["fastapi", "remotion", "cli"], help="Scaffold from template")
    parser.add_argument("--list-templates", action="store_true", help="List available templates")
    parser.add_argument("--lsp", action="store_true", help="Start LSP server (stdio)")
    parser.add_argument("--lsp-tcp", type=int, default=None, help="Start LSP on TCP port")
    args = parser.parse_args()

    configure_logging()

    if args.list_templates:
        from sick.templates import list_templates

        for t in list_templates():
            print(t)
        sys.exit(0)
    if args.template:
        from sick.templates import render_template

        dest = Path(args.task) if args.task else Path(".") / args.template
        out = render_template(args.template, dest)
        print(f"template {args.template} -> {out}")
        sys.exit(0)
    if args.lsp or args.lsp_tcp is not None:
        from sick.lsp.server import main as lsp_main

        lsp_main(tcp_port=args.lsp_tcp)
        sys.exit(0)

    workspace = Path(args.workspace or ".").resolve()
    cfg = load_config(workspace)
    model = args.model or cfg["model"] or None

    # .env precedence: exported env > workspace .env > sick install .env.
    # (providers.py already loaded the cwd .env at import; the install
    # fallback matters when `sick` runs globally outside the checkout.)
    from sick.providers import load_env

    load_env(workspace / ".env")
    if os.environ.get("SICK_ROOT"):
        load_env(Path(os.environ["SICK_ROOT"]) / ".env")

    if args.preflight:
        report, ok = preflight(str(workspace))
        print(report)
        sys.exit(0 if ok else 1)
    if os.environ.get("SICK_TRACING") == "1" or cfg.get("tracing"):
        try:
            from nooa.tracing import enable_tracing, exporters  # type: ignore

            enable_tracing(exporters=[exporters.jsonl(str(workspace / ".sick" / "traces"))])  # type: ignore
        except Exception:
            pass

    if args.setup:
        # Re-runnable setup: change provider/key even when one is already
        # configured (the first-run wizard below only fires with no key).
        if not sys.stdin.isatty():
            print("sick: --setup needs a terminal for hidden key entry.", file=sys.stderr)
            sys.exit(2)
        from sick.providers import prompt_for_api_key

        if not prompt_for_api_key(workspace / ".env"):
            print("sick: setup skipped — keeping the current configuration.", file=sys.stderr)
            sys.exit(2)
        load_env(workspace / ".env")

    try:
        provider = detect(model)
        llm = provider.create_llm()
    except ValueError as e:
        # first run on a terminal: offer the setup wizard instead of
        # telling the user to hand-edit a file they may not know about
        if sys.stdin.isatty():
            from sick.providers import prompt_for_api_key

            try:
                saved = prompt_for_api_key(workspace / ".env")
            except Exception:
                saved = False
            if saved:
                load_env(workspace / ".env")
                try:
                    provider = detect(model)
                    llm = provider.create_llm()
                except ValueError:
                    saved = False
            if not saved:
                print("sick: no API key configured — run `sick` again when you have one.", file=sys.stderr)
                sys.exit(2)
        else:
            print(f"sick: {e}", file=sys.stderr)
            print("hint: run `sick` in a terminal to set up a key, or export NVIDIA_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY", file=sys.stderr)
            sys.exit(2)

    set_default_strategy(CodeActStrategy(config=CodeActConfig(max_iterations=args.max_iterations)))

    agent = SickAgent(llm=llm, attachments=args.attach, workspace=workspace)

    if args.sandbox or os.environ.get("SICK_SANDBOX") == "1":
        agent.registry.set_sandboxed(True)
        print("sandbox: bash commands will run inside bwrap (beta)", file=sys.stderr)

    def _run_generation(coro) -> str:
        """Run one generation; surface LLM errors cleanly, never a traceback."""
        try:
            return asyncio.run(coro)
        except Exception as e:
            msg = str(e).replace("\n", " ")[:600]
            print(f"sick: turn failed: {msg}", file=sys.stderr)
            if "Request too large" in msg or "tokens per minute" in msg:
                print(
                    "hint: this provider's per-minute token limit is smaller than one Sick "
                    "agent request (~15k tokens incl. tool docs). On Groq's free tier (8k TPM) "
                    "no coding agent fits — upgrade to Groq Dev Tier or use another provider/model.",
                    file=sys.stderr,
                )
            sys.exit(1)

    if args.learn is not None:
        from sick.learn import build_learn_prompt

        brief = agent.learn_brief(args.learn)
        print(brief)
        agent.begin_run(build_learn_prompt(brief, args.learn), approved=True)
        result = _run_generation(agent.run(build_learn_prompt(brief, args.learn)))
        print(result)
        verdict = agent.finish_run("learn")
        if verdict is not None and not verdict.allowed:
            print(f"SDLC gate: BLOCKED — {'; '.join(verdict.reasons)}", file=sys.stderr)
    elif args.modify:
        agent.begin_run(args.modify, approved=True)
        result = _run_generation(agent.modify_self(args.modify))
        print(result)
        verdict = agent.finish_run("modify_self")
        if verdict is not None and not verdict.allowed:
            print(f"SDLC gate: BLOCKED — {'; '.join(verdict.reasons)}", file=sys.stderr)
            sys.exit(3)
    elif args.task:
        task = args.task
        # opencode-like: `sick /my-command args` expands custom command even in CLI one-shot
        if task.strip().startswith("/"):
            try:
                from sick.tui.commands import PromptCommand, SlashCommandRegistry, _expand_template

                reg = SlashCommandRegistry(workspace=workspace)
                line = task.strip()
                name = line[1:].split()[0].lower() if len(line) > 1 else ""
                argstr = line.split(maxsplit=1)[1] if " " in line else ""
                cmd = reg.commands.get(name)
                if isinstance(cmd, PromptCommand):
                    task = _expand_template(cmd.template, argstr, workspace, agent)
                    # model override for one-shot
                    if cmd.model:
                        try:
                            agent._llm = detect(cmd.model).create_llm()
                        except Exception:
                            pass
                    if cmd.agent_hint:
                        task = f"[agent: {cmd.agent_hint}]\n{task}"
            except Exception:
                pass
        agent.begin_run(task, approved=True)
        result = _run_generation(agent.run(task))
        print(result)
        verdict = agent.finish_run("one-shot task")
        if verdict is not None and not verdict.allowed:
            print(f"SDLC gate: BLOCKED — {'; '.join(verdict.reasons)}", file=sys.stderr)
            print(f"run artifacts: {agent.current_run.dir if agent.current_run else ''}", file=sys.stderr)
            sys.exit(3)
    else:
        from sick.tui import run_tui

        run_tui(agent)


if __name__ == "__main__":
    main()
