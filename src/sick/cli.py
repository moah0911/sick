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

    __version__ = _pkg_version("sick")
except Exception:
    __version__ = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser(prog="sick", description="Self-improving coding agent")
    parser.add_argument("task", nargs="?", help="Task to perform")
    parser.add_argument("--modify", help="Self-modification instruction")
    parser.add_argument("--attach", action="append", default=[], help="Attach a file (PDF parsed via Docling)")
    parser.add_argument("--workspace", default=None, help="Project directory to work in (default: .)")
    parser.add_argument("--model", default=None, help="Override the LLM model")
    parser.add_argument("--max-iterations", type=int, default=25, help="CodeAct max iterations")
    parser.add_argument("--sandbox", action="store_true", help="Run bash inside a bwrap sandbox (beta)")
    parser.add_argument("--preflight", action="store_true", help="Run health checks and exit")
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

    provider = detect(model)
    llm = provider.create_llm()

    set_default_strategy(CodeActStrategy(config=CodeActConfig(max_iterations=args.max_iterations)))

    agent = SickAgent(llm=llm, attachments=args.attach, workspace=workspace)

    if args.sandbox or os.environ.get("SICK_SANDBOX") == "1":
        agent._tools["bash"].sandboxed = True
        print("sandbox: bash commands will run inside bwrap (beta)", file=sys.stderr)

    if args.modify:
        result = asyncio.run(agent.modify_self(args.modify))
        print(result)
    elif args.task:
        result = asyncio.run(agent.run(args.task))
        print(result)
    else:
        from sick.tui import run_tui

        run_tui(agent)


if __name__ == "__main__":
    main()
