"""
The three packages keep to their layers: core imports neither app nor engine, and app and engine never import
each other (docs/RUNNER_SEPARATION.md). Reads the source with ast, so imports inside functions count too.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Imports that still cross the line. Each one has a plan to go; none may be added.
KNOWN_EXCEPTIONS = {
    # The delivery command's no-API path loads records straight into the database. Goes in Phase B.
    ("engine/spool_delivery.py", "app"),
}


def packages_imported_by(path: Path) -> set:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def crossings(package: str, forbidden: set) -> list:
    found = []
    for path in sorted((ROOT / package).rglob("*.py")):
        relative = str(path.relative_to(ROOT))
        for name in packages_imported_by(path) & forbidden:
            if (relative, name) not in KNOWN_EXCEPTIONS:
                found.append(f"{relative} imports {name}")
    return found


def test_core_imports_neither_app_nor_engine():
    assert crossings("core", {"app", "engine"}) == []


def test_app_does_not_import_engine():
    assert crossings("app", {"engine"}) == []


def test_engine_does_not_import_app():
    assert crossings("engine", {"app"}) == []


def test_every_known_exception_is_still_needed():
    stale = [f"{path} no longer imports {name}" for path, name in sorted(KNOWN_EXCEPTIONS)
             if name not in packages_imported_by(ROOT / path)]
    assert stale == []
