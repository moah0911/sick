import subprocess

from sick.tools.base import ToolResult, WorkspaceTool

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

    def execute(self, message: str = "checkpoint") -> ToolResult:
        if not _in_repo(self.root):
            return ToolResult.failure("[error: not a git repository]", tool=self.name)
        if _is_clean(self.root):
            return ToolResult.success("no changes to checkpoint", tool=self.name)
        # remember where to return to (branch name, or commit if detached)
        cur = _git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        cur_head = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        back = cur if cur and cur != "HEAD" else cur_head
        # create the checkpoint branch ref without switching, then switch —
        # every step is checked: committing anywhere but the checkpoint
        # branch would break this tool's core promise
        if _git(self.root, "rev-parse", "--verify", CHECKPOINT_BRANCH).returncode != 0:
            r = _git(self.root, "branch", CHECKPOINT_BRANCH)
            if r.returncode != 0:
                return ToolResult.failure(f"[error: checkpoint failed: {r.stderr.strip()}]", tool=self.name)
        r = _git(self.root, "checkout", CHECKPOINT_BRANCH)
        if r.returncode != 0:
            return ToolResult.failure(f"[error: checkpoint failed: {r.stderr.strip()}]", tool=self.name)
        if _git(self.root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != CHECKPOINT_BRANCH:
            _git(self.root, "checkout", back)
            return ToolResult.failure("[error: checkpoint failed: could not switch to checkpoint branch]", tool=self.name)
        _git(self.root, "add", "-A")
        r = _git(self.root, "commit", "-m", f"[sick] {message}")
        # get hash reliably
        h = _git(self.root, "rev-parse", "HEAD").stdout.strip() if r.returncode == 0 else ""
        # return to original branch
        _git(self.root, "checkout", back)
        if r.returncode != 0:
            return ToolResult.failure(f"[error: checkpoint failed: {r.stderr.strip()}]", tool=self.name)
        short = h[:7] if h else r.stdout.strip().split()[-1]
        return ToolResult.success(f"checkpoint created: {short}", tool=self.name)


class Restore(WorkspaceTool):
    name = "restore"
    description = "Restore the workspace from the latest (or n-th most recent) sick checkpoint"

    def execute(self, n: int = 1) -> ToolResult:
        if not _in_repo(self.root):
            return ToolResult.failure("[error: not a git repository]", tool=self.name)
        if _git(self.root, "rev-parse", "--verify", CHECKPOINT_BRANCH).returncode != 0:
            return ToolResult.failure("[error: no checkpoints found]", tool=self.name)
        ref = f"{CHECKPOINT_BRANCH}~{n - 1}" if n > 1 else CHECKPOINT_BRANCH
        if _git(self.root, "rev-parse", "--verify", f"{ref}^{{commit}}").returncode != 0:
            return ToolResult.failure(f"[error: checkpoint {n} does not exist]", tool=self.name)
        r = _git(self.root, "restore", "--source", ref, "--worktree", "--staged", ".")
        # remove untracked files created after checkpoint
        if r.returncode == 0:
            _git(self.root, "clean", "-fd")
        # fallback for older git without restore
        if r.returncode != 0:
            r = _git(self.root, "checkout", ref, "--", ".")
            if r.returncode == 0:
                _git(self.root, "clean", "-fd")
        if r.returncode != 0:
            return ToolResult.failure(f"[error: restore failed: {r.stderr.strip()}]", tool=self.name)
        return ToolResult.success(f"workspace restored from checkpoint {n}", tool=self.name)


class ListCheckpoints(WorkspaceTool):
    name = "checkpoints"
    description = "List sick checkpoints (most recent first)"

    def execute(self) -> ToolResult:
        if not _in_repo(self.root):
            return ToolResult.failure("[error: not a git repository]", tool=self.name)
        r = _git(self.root, "log", CHECKPOINT_BRANCH, "--oneline", "-20")
        if r.returncode != 0:
            return ToolResult.failure("[error: no checkpoints found]", tool=self.name)
        out = r.stdout.strip()
        return ToolResult.success(out, tool=self.name) if out else ToolResult.failure("[error: no checkpoints found]", tool=self.name)