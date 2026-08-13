import subprocess

from sick.tools.base import WorkspaceTool


CHECKPOINT_BRANCH = "sick-checkpoints"


def _git(root, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=root,
    )


def _in_repo(root) -> bool:
    return _git(root, "rev-parse", "--is-inside-work-tree").returncode == 0


def _is_clean(root) -> bool:
    r = _git(root, "status", "--porcelain")
    return r.returncode == 0 and not r.stdout.strip()


class Checkpoint(WorkspaceTool):
    name = "checkpoint"
    description = "Commit all workspace changes to the sick-checkpoints branch (never touches the working branch)"

    def execute(self, message: str = "checkpoint") -> str:
        if not _in_repo(self.root):
            return "[error: not a git repository]"
        if _is_clean(self.root):
            return "no changes to checkpoint"
        if _git(self.root, "rev-parse", "--verify", CHECKPOINT_BRANCH).returncode != 0:
            _git(self.root, "checkout", "-b", CHECKPOINT_BRANCH)
        else:
            _git(self.root, "checkout", CHECKPOINT_BRANCH)
        _git(self.root, "add", "-A")
        r = _git(self.root, "commit", "-m", f"[sick] {message}")
        _git(self.root, "checkout", "-")
        if r.returncode != 0:
            return f"[error: checkpoint failed: {r.stderr.strip()}]"
        return f"checkpoint created: {r.stdout.strip().split()[-1]}"


class Restore(WorkspaceTool):
    name = "restore"
    description = "Restore the workspace from the latest (or n-th most recent) sick checkpoint"

    def execute(self, n: int = 1) -> str:
        if not _in_repo(self.root):
            return "[error: not a git repository]"
        if _git(self.root, "rev-parse", "--verify", CHECKPOINT_BRANCH).returncode != 0:
            return "[error: no checkpoints found]"
        ref = f"{CHECKPOINT_BRANCH}~{n - 1}" if n > 1 else CHECKPOINT_BRANCH
        if _git(self.root, "rev-parse", "--verify", f"{ref}^{{commit}}").returncode != 0:
            return f"[error: checkpoint {n} does not exist]"
        r = _git(self.root, "restore", "--source", ref, "--worktree", "--staged", ".")
        if r.returncode != 0:
            return f"[error: restore failed: {r.stderr.strip()}]"
        return f"workspace restored from checkpoint {n}"


class ListCheckpoints(WorkspaceTool):
    name = "checkpoints"
    description = "List sick checkpoints (most recent first)"

    def execute(self) -> str:
        if not _in_repo(self.root):
            return "[error: not a git repository]"
        r = _git(self.root, "log", CHECKPOINT_BRANCH, "--oneline", "-20")
        if r.returncode != 0:
            return "[error: no checkpoints found]"
        return r.stdout.strip() or "[error: no checkpoints found]"