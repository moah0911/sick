import os
import shutil
import subprocess


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}


def preflight(workspace: str) -> str:
    """Run the cheap health checks before starting work."""
    lines = [f"workspace: {workspace}"]
    ok = True

    import_check = subprocess.run(
        ["uv", "run", "python", "-c", "from sick.agent import SickAgent; SickAgent()"],
        capture_output=True,
        text=True,
        cwd=workspace,
        env=_clean_env(),
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

    if shutil.which("pytest"):
        pytest = subprocess.run(
            ["uv", "run", "pytest", "-q"], capture_output=True, text=True, cwd=workspace,
            env=_clean_env(),
        )
        summary = pytest.stdout.strip().splitlines()[-1] if pytest.stdout.strip() else "no tests found"
        lines.append(f"pytest: {summary}")
        if pytest.returncode != 0:
            ok = False
    else:
        lines.append("pytest: not installed")

    lines.append("preflight: " + ("ok" if ok else "FAILED"))
    return "\n".join(lines), ok