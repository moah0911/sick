"""Sick LSP server — pygls stdio/tcp, hover via CodeResearch."""
import re
from pathlib import Path
try:
    from pygls.server import LanguageServer
    from lsprotocol import types as lsp
except Exception:
    LanguageServer = None
    lsp = None
from sick.config import load_config
from sick.tools.research import CodeIndex
def _get_word(line: str, col: int) -> str:
    m = re.findall(r"\w+", line)
    pos = 0
    for w in m:
        idx = line.find(w, pos)
        if idx <= col < idx + len(w):
            return w
        pos = idx + len(w)
    return m[0] if m else ""
class SickLanguageServer(LanguageServer):
    def __init__(self, *a, **kw):
        super().__init__("sick-lsp", "v0.1.0", *a, **kw)
        self.index = None
        self.root = Path.cwd()
    def _ensure_index(self, root: Path) -> None:
        self.root = root.resolve()
        cfg = load_config(self.root)
        idx = CodeIndex(str(self.root))
        idx.excluded = set(idx.excluded) | set(cfg.get("excluded") or [])
        idx.build()
        self.index = idx
def create_server():
    if LanguageServer is None:
        raise RuntimeError("pygls not installed. Run: uv sync --extra lsp")
    server = SickLanguageServer()
    @server.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
    @server.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
    async def did_open(ls, params):
        uri = params.text_document.uri
        try:
            p = Path(uri.replace("file://", "")).resolve()
            rel = p.relative_to(ls.root)
            if ls.index and ls.index._is_ignored(rel):
                diag = lsp.Diagnostic(range=lsp.Range(start=lsp.Position(line=0, character=0), end=lsp.Position(line=0, character=5)), message=f"sick: excluded path '{rel.parts[0]}' — skipped by index", severity=lsp.DiagnosticSeverity.Hint, source="sick")
                ls.publish_diagnostics(uri, [diag])
            else:
                ls.publish_diagnostics(uri, [])
        except Exception:
            pass
    @server.feature(lsp.TEXT_DOCUMENT_HOVER)
    async def hover(ls, params):
        if ls.index is None:
            return None
        uri = params.text_document.uri
        doc = ls.workspace.get_text_document(uri)
        line = doc.lines[params.position.line] if params.position.line < len(doc.lines) else ""
        word = _get_word(line, params.position.character)
        if not word:
            return None
        hits = ls.index.search(f"{word} {line.strip()}", k=3)
        if not hits:
            return None
        md = "\n\n".join(f"**{h.chunk.path}:{h.chunk.start}** {h.chunk.kind} `{h.chunk.name}` (score {h.score:.1f})\n```py\n{h.chunk.content[:400]}\n```" for h in hits)
        return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=md))
    @server.feature(lsp.INITIALIZE)
    async def initialize(ls, params):
        root = None
        if getattr(params, "workspace_folders", None):
            for f in params.workspace_folders:
                root = Path(f.uri.replace("file://", ""))
                break
        if not root:
            root = Path(getattr(params, "root_path", None) or getattr(params, "root_uri", None) or ".")
            if isinstance(root, str) and root.startswith("file://"):
                root = Path(root.replace("file://", ""))
        try:
            ls._ensure_index(Path(root))
        except Exception:
            ls._ensure_index(Path.cwd())
        ls.show_message("sick-lsp indexed", msg_type=lsp.MessageType.Info)
    return server
def main(tcp_port=None):
    server = create_server()
    if tcp_port:
        server.start_tcp("127.0.0.1", tcp_port)
    else:
        server.start_io()
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--tcp", type=int, default=None)
    args = p.parse_args()
    main(tcp_port=args.tcp)
