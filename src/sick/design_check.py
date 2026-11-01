"""Deterministic OO/design checks over changed Python files (AST only).

Hard issues (syntax errors, duplicate top-level definitions) block delivery.
Warnings (oversized classes, private-attribute access) are recorded, never
silently ignored. This is enforcement in code, not prompt advice.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

MAX_CLASS_METHODS = 20
MAX_CLASS_LINES = 300


@dataclass
class DesignIssue:
    level: str  # "hard" | "warn"
    message: str
    path: str


def analyze_file(path: str | Path, root: str | Path | None = None) -> list[DesignIssue]:
    p = Path(path)
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return []
    rel = str(p.relative_to(Path(root).resolve())) if root else str(p)
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return [DesignIssue("hard", f"syntax error in {rel}: {e}", rel)]
    issues: list[DesignIssue] = []
    seen: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen:
                issues.append(
                    DesignIssue("hard", f"duplicate top-level definition '{node.name}' in {rel}", rel)
                )
            seen[node.name] = seen.get(node.name, 0) + 1
    for walked in ast.walk(tree):
        if isinstance(walked, ast.ClassDef):
            methods = sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in walked.body)
            span = (walked.end_lineno or walked.lineno) - walked.lineno + 1
            if methods > MAX_CLASS_METHODS:
                issues.append(DesignIssue("warn", f"class '{walked.name}' in {rel} has {methods} methods (>{MAX_CLASS_METHODS})", rel))
            if span > MAX_CLASS_LINES:
                issues.append(DesignIssue("warn", f"class '{walked.name}' in {rel} spans {span} lines (>{MAX_CLASS_LINES})", rel))
        elif isinstance(walked, ast.Attribute) and walked.attr.startswith("_") and not walked.attr.startswith("__"):
            if not (isinstance(walked.value, ast.Name) and walked.value.id in {"self", "cls"}):
                issues.append(DesignIssue("warn", f"private access '.{walked.attr}' in {rel}:{walked.lineno}", rel))
    return issues


def analyze_files(paths, root: str | Path) -> list[DesignIssue]:
    issues: list[DesignIssue] = []
    base = Path(root).resolve()
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = base / p
        if p.suffix == ".py" and p.is_file():
            issues.extend(analyze_file(p, base))
    return issues
