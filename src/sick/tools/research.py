"""Code research: our own codebase index.

- index: ast-based function/class chunks for .py, 100-line bands otherwise
- search: weighted token overlap (name hits > prefix hits > body hits)
- research: top-k chunks rendered with paths for the agent to read

ponytail: lexical scoring only. If natural-language recall falls short, add
embeddings via litellm.embedding (already a nooa dep) behind this API.
"""

import ast
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from sick.tools.base import EXCLUDED_DIRS, WorkspaceTool

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "have", "has",
    "are", "was", "were", "will", "would", "should", "could", "can", "not",
    "into", "over", "under", "than", "then", "there", "here", "what", "how",
    "why", "when", "where", "which", "your", "you", "our", "their", "its",
    "all", "any", "some", "each", "other", "about", "after", "before",
}

CODE_EXT = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".c",
    ".cpp", ".h", ".hpp", ".rb", ".php", ".sh", ".md", ".toml", ".yaml",
    ".yml", ".json", ".css", ".html", ".sql",
}
MAX_FILE_BYTES = 500_000
CHUNK_LINES = 100
_IDENT = re.compile(r"[a-z0-9_]+|[A-Z][a-z0-9_]*")


def tokenize(text: str) -> list[str]:
    words = [w.lower() for w in _IDENT.findall(text)]
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


@dataclass
class Chunk:
    path: str  # relative to index root
    kind: str  # "function" | "class" | "file"
    name: str
    start: int
    end: int
    content: str


@dataclass
class Hit:
    chunk: Chunk
    score: float


class CodeIndex:
    """Codebase index: ast chunks + lexical scoring, cached by mtime."""

    def __init__(self, root: str = ".") -> None:
        self.root = Path(root).resolve()
        self.chunks: list[Chunk] = []
        self.build_time = 0.0
        self.file_count = 0

    def build(self) -> int:
        started = time.monotonic()
        files = self._iter_files()
        mtimes = {
            str(f.relative_to(self.root)): [f.stat().st_mtime_ns, f.stat().st_size]
            for f in files
        }
        cached = self._load(mtimes)
        if cached is not None:
            self.chunks = cached
        else:
            self.chunks = []
            for f in files:
                self.chunks.extend(self._chunk_file(f))
            self._save(mtimes)
        self.file_count = len(mtimes)
        self.build_time = time.monotonic() - started
        return len(self.chunks)

    def _iter_files(self) -> list[Path]:
        files = []
        for p in self.root.rglob("*"):
            if not p.is_file() or p.suffix not in CODE_EXT:
                continue
            rel = p.relative_to(self.root)
            if self._is_ignored(rel):
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            files.append(p)
        return sorted(files)

    @staticmethod
    def _is_ignored(rel: Path) -> bool:
        return any(
            part.startswith(".") or part in EXCLUDED_DIRS
            for part in rel.parts
        )

    def _chunk_file(self, path: Path) -> list[Chunk]:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            return []
        rel = path.relative_to(self.root)
        if path.suffix == ".py":
            try:
                tree = ast.parse(text)
            except SyntaxError:
                pass
            else:
                chunks = self._chunk_python(rel, text, tree)
                return chunks or self._chunk_lines(rel, text)
        return self._chunk_lines(rel, text)

    def _chunk_python(self, rel: Path, text: str, tree: ast.AST) -> list[Chunk]:
        chunks = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seg = ast.get_source_segment(text, node) or ""
                chunks.append(
                    Chunk(
                        path=str(rel),
                        kind="class" if isinstance(node, ast.ClassDef) else "function",
                        name=node.name,
                        start=node.lineno,
                        end=node.end_lineno or node.lineno,
                        content=seg,
                    )
                )
        return chunks

    def _chunk_lines(self, rel: Path, text: str) -> list[Chunk]:
        lines = text.splitlines()
        chunks = []
        for i in range(0, len(lines), CHUNK_LINES):
            seg = lines[i : i + CHUNK_LINES]
            chunks.append(
                Chunk(
                    path=str(rel),
                    kind="file",
                    name=rel.stem,
                    start=i + 1,
                    end=i + len(seg),
                    content="\n".join(seg),
                )
            )
        return chunks

    def search(self, query: str, k: int = 8) -> list[Hit]:
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scored = [Hit(c, self._score(c, q_tokens)) for c in self.chunks]
        scored = [h for h in scored if h.score > 0]
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:k]

    def _score(self, chunk: Chunk, q_tokens: list[str]) -> float:
        lines = chunk.content.splitlines()
        head = lines[0] if lines else ""
        name_tokens = set(tokenize(chunk.name)) | set(tokenize(head))
        body_tokens = set(tokenize(chunk.content))
        score = 0.0
        for t in q_tokens:
            if t in name_tokens:
                score += 4.0
            elif any(w.startswith(t) for w in name_tokens) or any(w.startswith(t) for w in body_tokens):
                score += 2.0
            elif t in chunk.content.lower():
                score += 1.0
        return score

    def research(self, query: str, k: int = 8) -> str:
        hits = self.search(query, k)
        if not hits:
            return f"no matching code found for: {query}"
        lines = [f"## {query}"]
        for h in hits:
            c = h.chunk
            head = (c.content.splitlines() or [""])[0]
            lines.append(
                f"- `{c.path}:{c.start}` — {c.kind} `{c.name}` (score {h.score:.1f})"
            )
            if head:
                lines.append(f"  ```\n  {head}\n  ```")
        return "\n".join(lines)

    def status(self) -> str:
        return (
            f"indexed {len(self.chunks)} chunks from {self.file_count} files "
            f"({self.build_time:.1f}s, cached at {self._cache_path()})"
        )

    # ── cache ──

    def _cache_path(self) -> Path:
        return self.root / ".sick" / "indexes" / "code-index.json"

    def _load(self, mtimes: dict[str, list[int]]) -> list[Chunk] | None:
        try:
            data = json.loads(self._cache_path().read_text())
            if data.get("mtimes") != mtimes:
                return None
            return [Chunk(**c) for c in data["chunks"]]
        except (OSError, ValueError, TypeError, KeyError):
            return None

    def _save(self, mtimes: dict[str, list[int]]) -> None:
        try:
            self._cache_path().parent.mkdir(parents=True, exist_ok=True)
            payload = {"mtimes": mtimes, "chunks": [asdict(c) for c in self.chunks]}
            tmp = self._cache_path().with_suffix(".tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(self._cache_path())
        except OSError:
            pass


class CodeResearch(WorkspaceTool):
    """Search the codebase index for code relevant to a query."""

    name = "code_research"
    description = (
        "Search the codebase index for chunks (functions/classes/files) relevant "
        "to a natural-language query — returns paths + line ranges to read."
    )

    def __init__(self, root: str = ".") -> None:
        super().__init__(root)
        self.index = CodeIndex(str(self.root))
        self.chunk_count = self.index.build()

    def execute(self, query: str, k: int = 8) -> str:
        return self.index.research(query, k)
