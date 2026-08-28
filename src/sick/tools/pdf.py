import importlib.util
import re

from sick.tools.base import WorkspaceTool

_PAGE_RANGE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?$")


def parse_page_ranges(pages: str) -> list[tuple[int, int]]:
    """Turn a page expression such as ``1-5,8`` into inclusive ranges."""
    if not pages.strip():
        raise ValueError("page selection must not be empty")
    ranges: list[tuple[int, int]] = []
    for part in pages.split(","):
        match = _PAGE_RANGE.fullmatch(part.strip())
        if not match:
            raise ValueError(f"invalid page range: {part!r}")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < start:
            raise ValueError(f"invalid page range: {part!r}")
        ranges.append((start, end))
    return ranges


class ParsePdf(WorkspaceTool):
    name = "parse_pdf"
    description = "Parse a PDF into clean Markdown using Docling — preserves structure (headings, tables, lists)"

    def available(self) -> bool:
        return importlib.util.find_spec("docling") is not None

    def execute(self, path: str) -> str:
        if not self.available():
            return (
                "Docling not installed. Run: uv sync --extra pdf\n"
                "Docling converts PDFs to clean Markdown — far better than pdftotext or OCR."
            )
        try:
            source = self.resolve_path(path)
            if not source.is_file() or source.suffix.lower() != ".pdf":
                return f"Error: {path} is not a PDF file in the workspace"
            from docling.document_converter import DocumentConverter
            result = DocumentConverter().convert(source)
            return result.document.export_to_markdown()
        except Exception as e:
            return f"[error parsing PDF: {e}]"

    def execute_pages(self, path: str, pages: str) -> str:
        """Parse specific pages. pages='1-5,8'"""
        if not self.available():
            return "Docling not installed. Run: uv sync --extra pdf"
        try:
            source = self.resolve_path(path)
            if not source.is_file() or source.suffix.lower() != ".pdf":
                return f"Error: {path} is not a PDF file in the workspace"
            page_ranges = parse_page_ranges(pages)
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
            return "\n\n".join(
                converter.convert(source, page_range=page_range).document.export_to_markdown()
                for page_range in page_ranges
            )
        except Exception as e:
            return f"[error parsing PDF: {e}]"
