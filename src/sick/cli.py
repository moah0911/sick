import argparse
import asyncio
import os
import sys
from pathlib import Path

from nooa import CodeActStrategy, set_default_strategy
from nooa.config import CodeActConfig

from sick import SickAgent, detect
from sick.config import load_config
from sick.preflight import preflight


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
    args = parser.parse_args()

    workspace = Path(args.workspace or ".").resolve()
    cfg = load_config(workspace)
    model = args.model or cfg["model"] or None

    if args.preflight:
        report, ok = preflight(str(workspace))
        print(report)
        sys.exit(0 if ok else 1)

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