"""Template scaffolding — ponytail: thin wrapper over cookiecutter, fallback copytree."""
from pathlib import Path

BUILTIN = {"fastapi", "remotion", "cli"}


def _templates_dir() -> Path:
    pkg = Path(__file__).parent / "templates"
    if pkg.exists():
        return pkg
    root = Path(__file__).resolve().parents[2] / "templates"
    return root


def list_templates() -> list[str]:
    d = _templates_dir()
    if not d.exists():
        return sorted(BUILTIN)
    return sorted([p.name for p in d.iterdir() if p.is_dir()])


def render_template(name: str, dest: str | Path, extra: dict | None = None, no_input: bool = True) -> str:
    if name not in BUILTIN and name not in list_templates():
        raise ValueError(f"unknown template: {name} (available: {', '.join(list_templates())})")
    dest_path = Path(dest)
    if dest_path.exists() and any(dest_path.iterdir()):
        raise ValueError(f"destination {dest_path} already exists and is not empty")
    src = _templates_dir() / name
    if not src.exists():
        raise ValueError(f"template {name} not found at {src}")
    try:
        from cookiecutter.main import cookiecutter  # type: ignore
        parent = dest_path.parent.resolve()
        parent.mkdir(parents=True, exist_ok=True)
        ctx = {"project_slug": dest_path.name}
        if extra:
            ctx.update(extra)
        out = cookiecutter(
            str(src),
            output_dir=str(parent),
            no_input=no_input,
            extra_context=ctx,
            overwrite_if_exists=False,
        )
        return out
    except Exception as e:
        import shutil
        import string
        fallback_src = src / "{{cookiecutter.project_slug}}"
        if not fallback_src.exists():
            fallback_src = src
        dest_path.mkdir(parents=True, exist_ok=True)
        for item in fallback_src.rglob("*"):
            if item.is_dir():
                continue
            rel = item.relative_to(fallback_src)
            target = dest_path / str(rel).replace("{{cookiecutter.project_slug}}", dest_path.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                text = item.read_text()
                tmpl = string.Template(text)
                text = tmpl.safe_substitute(project_slug=dest_path.name, project_name=dest_path.name)
                target.write_text(text)
            except Exception:
                shutil.copy2(item, target)
        if isinstance(e, ImportError):
            raise
        return str(dest_path)
