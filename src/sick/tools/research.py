"""Code research: codebase index with hybrid lexical + embeddings.

- index: ast chunks + 100-line bands
- search: lexical 4/2/1 + optional litellm embeddings (SICK_EMBED_MODEL), RRF hybrid via numpy cosine
- research: top-k rendered

ponytail: numpy cosine batch; litellm via nooa, fallback lexical; vectors cached at .sick/indexes/vectors.npz
"""

import ast
import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from sick.tools.base import EXCLUDED_DIRS, WorkspaceTool

try:
    import numpy as np  # type: ignore

    HAS_NUMPY = True
except Exception:  # pragma: no cover
    np = None  # type: ignore
    HAS_NUMPY = False

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
EMBED_CACHE_VERSION = 1


def _get_embed_model() -> str | None:
    return os.environ.get("SICK_EMBED_MODEL", "").strip() or None


def _get_max_bytes() -> int:
    try:
        v = int(os.environ.get("SICK_MAX_READ_BYTES", str(MAX_FILE_BYTES)))
        return max(10_000, min(10_000_000, v))
    except ValueError:
        return MAX_FILE_BYTES


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _batch_cosine(matrix, q) -> list[float]:
    if HAS_NUMPY and matrix is not None:
        try:
            import numpy as _np  # type: ignore
            q_arr = _np.array(q, dtype=_np.float32)
            qn = q_arr / _np.linalg.norm(q_arr) if _np.linalg.norm(q_arr) else q_arr
            m = _np.array(matrix, dtype=_np.float32)
            norms = _np.linalg.norm(m, axis=1, keepdims=True)
            norms[norms == 0] = 1
            mn = m / norms
            scores = (mn @ qn).tolist()
            return [float(s) for s in scores]
        except Exception:
            pass
    return [_cosine(row, q) for row in matrix] if matrix is not None else []


def tokenize(text: str) -> list[str]:
    words = [w.lower() for w in _IDENT.findall(text)]
    return [w for w in words if len(w) > 1 and w not in STOPWORDS]


@dataclass
class Chunk:
    path: str
    kind: str
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
        self.excluded: set[str] = set(EXCLUDED_DIRS)
        self.embed_model: str | None = _get_embed_model()
        self.embeddings: list[list[float]] | None = None
        self._embed_provider: str = os.environ.get("SICK_EMBED_PROVIDER", "auto")

    def _embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        model = self.embed_model
        if not model:
            return None
        try:
            import litellm  # type: ignore
            vecs: list[list[float]] = []
            batch = 64
            for i in range(0, len(texts), batch):
                chunk = [t[:8000] for t in texts[i : i + batch]]
                kwargs = {}
                base = os.environ.get("SICK_BASE_URL")
                if base:
                    kwargs["api_base"] = base.rstrip("/")
                resp = litellm.embedding(model=model, input=chunk, **kwargs)  # type: ignore
                for d in resp.data:  # type: ignore
                    emb = d["embedding"] if isinstance(d, dict) else getattr(d, "embedding", [])
                    vecs.append(list(emb))
            return vecs
        except Exception:
            if self._embed_provider == "auto":
                try:
                    from sentence_transformers import SentenceTransformer  # type: ignore
                    mname = os.environ.get("SICK_EMBED_LOCAL_MODEL", "all-MiniLM-L6-v2")
                    model_l = SentenceTransformer(mname)
                    return [v.tolist() for v in model_l.encode(texts, normalize_embeddings=False)]  # type: ignore
                except Exception:
                    pass
            return None

    def _vectors_path(self) -> Path:
        return self.root / ".sick" / "indexes" / "vectors.npz"

    def _load_vectors(self) -> list[list[float]] | None:
        p = self._vectors_path()
        if not p.exists() or not self.embed_model:
            return None
        try:
            import numpy as _np  # type: ignore
            data = _np.load(str(p), allow_pickle=True)
            if str(data.get("model", "")) != self.embed_model:
                return None
            if int(data.get("version", 0)) != EMBED_CACHE_VERSION:
                return None
            vecs = data["vectors"]
            if len(vecs) != len(self.chunks):
                return None
            return [list(v) for v in vecs]
        except Exception:
            return None

    def _save_vectors(self) -> None:
        if not self.embeddings or not self.embed_model:
            return
        try:
            import numpy as _np  # type: ignore
            p = self._vectors_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            _np.savez_compressed(str(tmp), vectors=_np.array(self.embeddings, dtype=_np.float32), model=self.embed_model, version=EMBED_CACHE_VERSION)
            tmp.replace(p)
        except Exception:
            pass

    def build(self) -> int:
        started = time.monotonic()
        self.embed_model = _get_embed_model()
        self._embed_provider = os.environ.get("SICK_EMBED_PROVIDER", "auto")
        limit = _get_max_bytes()
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
        if self.embed_model and self.chunks:
            vecs = self._load_vectors()
            if vecs is None or len(vecs) != len(self.chunks):
                vecs = self._embed_texts([c.content for c in self.chunks])
                self.embeddings = vecs
                if vecs:
                    self._save_vectors()
                else:
                    self.embeddings = None
            else:
                self.embeddings = vecs
        else:
            self.embeddings = None
        self.file_count = len(mtimes)
        self.build_time = time.monotonic() - started
        return len(self.chunks)

    def _iter_files(self) -> list[Path]:
        files = []
        limit = _get_max_bytes()
        for p in self.root.rglob("*"):
            if not p.is_file() or p.suffix not in CODE_EXT:
                continue
            rel = p.relative_to(self.root)
            if self._is_ignored(rel):
                continue
            try:
                if p.stat().st_size > limit:
                    continue
            except OSError:
                continue
            files.append(p)
        return sorted(files)

    def _is_ignored(self, rel: Path) -> bool:
        excluded = getattr(self, "excluded", EXCLUDED_DIRS)
        return any(
            part.startswith(".") or part in excluded
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
        if self.embeddings and self.embed_model:
            try:
                q_vecs = self._embed_texts([query])
                if q_vecs and q_vecs[0]:
                    q_vec = q_vecs[0]
                    lex = [self._score(c, q_tokens) for c in self.chunks]
                    max_lex = max(lex) if lex else 1.0
                    lex_n = [s / max_lex if max_lex else 0 for s in lex]
                    cos = _batch_cosine(self.embeddings, q_vec)
                    hybrid_alpha = 0.7
                    try:
                        hybrid_alpha = float(os.environ.get("SICK_HYBRID_ALPHA", "0.7"))
                    except ValueError:
                        hybrid_alpha = 0.7
                    scores = [hybrid_alpha * c + (1 - hybrid_alpha) * l for c, l in zip(cos, lex_n)]
                    scored = [Hit(c, s) for c, s in zip(self.chunks, scores) if s > 0]
                    scored.sort(key=lambda h: h.score, reverse=True)
                    return scored[:k]
            except Exception:
                pass
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
        k = max(1, min(k, 50))
        hits = self.search(query, k)
        if not hits:
            return f"no matching code found for: {query}"
        lines = [f"## {query}"]
        for h in hits:
            c = h.chunk
            preview = "\n".join((c.content.splitlines() or [""])[:3])
            lines.append(
                f"- `{c.path}:{c.start}` — {c.kind} `{c.name}` (score {h.score:.1f})"
            )
            if preview.strip():
                lines.append(f"  ```\n  {preview[:400]}\n  ```")
        return "\n".join(lines)

    def status(self) -> str:
        emb = f", embeddings: {self.embed_model} ({len(self.embeddings or [])} vectors)" if self.embed_model and self.embeddings else (f", embeddings: {self.embed_model} (no vectors)" if self.embed_model else ", embeddings: disabled")
        return (
            f"indexed {len(self.chunks)} chunks from {self.file_count} files "
            f"({self.build_time:.1f}s, cached at {self._cache_path()}{emb})"
        )

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
            tmp = self._cache_path().parent / (self._cache_path().name + ".tmp")
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
