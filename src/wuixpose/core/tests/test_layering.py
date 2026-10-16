"""Import layering in core: constants, then models, then services, then api/tiles/views/commands.

A module may import from layers below its own, never above, so core can grow without import
cycles. Imports are read from source, including those under TYPE_CHECKING.
"""

import ast
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parent.parent
SRC = CORE.parent.parent
# What serves requests or runs commands. Nothing below it may import it.
TOP = ("wuixpose.core.api", "wuixpose.core.tiles", "wuixpose.core.views", "wuixpose.core.management")


def _module(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts)


def _within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(f"{prefix}.") for prefix in prefixes)


def _imports(path: Path) -> set[str]:
    """Absolute names of everything a file imports, modules and the names taken from them."""
    package = _module(path).split(".")[:-1]
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return {name for name in names if _within(name, ("wuixpose",))}


def _source_files() -> list[Path]:
    return sorted(p for p in CORE.rglob("*.py") if "tests" not in p.relative_to(CORE).parts)


def test_constants_import_nothing_from_wuixpose():
    assert _imports(CORE / "constants.py") == set()


@pytest.mark.parametrize("path", sorted((CORE / "models").glob("*.py")), ids=lambda p: p.name)
def test_models_import_only_constants_and_models(path):
    allowed = ("wuixpose.core.constants", "wuixpose.core.models")
    assert {name for name in _imports(path) if not _within(name, allowed)} == set()


@pytest.mark.parametrize(
    "path",
    [p for p in _source_files() if not _within(_module(p), TOP)],
    ids=lambda p: str(p.relative_to(CORE)),
)
def test_nothing_below_top_imports_it(path):
    assert {name for name in _imports(path) if _within(name, TOP)} == set()
