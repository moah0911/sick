import os
import shutil
import subprocess


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}


def preflight(workspace: str) -> tuple[str, bool]:
    """Run the cheap health checks before starting work."""
    lines = [f"workspace: {workspace}"]
    ok = True

    import_check = subprocess.run(
        ["uv", "run", "python", "-c", "from sick.agent import SickAgent; SickAgent()"],
        capture_output=True,
        text=True,
        cwd=workspace,
        env=_clean_env(),
        timeout=30,
    )
    if import_check.returncode == 0:
        lines.append("import check: ok")
    else:
        ok = False
        lines.append(f"import check: FAILED\n{import_check.stderr.strip()[:2000]}")

    git = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, cwd=workspace
    )
    if git.returncode == 0:
        lines.append(f"git: working tree {'dirty' if git.stdout.strip() else 'clean'}")
    else:
        lines.append("git: not a repository")

    if shutil.which("uv"):
        try:
            pytest = subprocess.run(
                ["uv", "run", "pytest", "-q"], capture_output=True, text=True, cwd=workspace,
                env=_clean_env(), timeout=60,
            )
            summary = pytest.stdout.strip().splitlines()[-1] if pytest.stdout.strip() else "no tests found"
            if pytest.stderr.strip() and "passed" not in summary and "failed" not in summary:
                summary = pytest.stderr.strip().splitlines()[-1][:200]
            lines.append(f"pytest: {summary}")
            if pytest.returncode != 0:
                ok = False
        except subprocess.TimeoutExpired:
            lines.append("pytest: timed out")
            ok = False
    else:
        lines.append("pytest: uv not installed")
    # bwrap sandbox check
    if shutil.which("bwrap"):
        lines.append("bwrap: available (sandbox ready)")
    else:
        lines.append("bwrap: not installed (sandbox unavailable, use --sandbox to test)")
    # docling check
    try:
        import importlib.util as _ilu

        if _ilu.find_spec("docling") is not None:
            lines.append("docling: available (pdf ready)")
        else:
            lines.append("docling: not installed (uv sync --extra pdf)")
    except Exception:
        lines.append("docling: check failed")
    # node/npx check for remotion
    if shutil.which("npx"):
        lines.append("npx: available (remotion ready)")
    else:
        lines.append("npx: not installed (remotion /visual unavailable)")

    lines.append("preflight: " + ("ok" if ok else "FAILED"))
    return "\n".join(lines), ok