import ast
from pathlib import Path


def test_no_shop_imports():
    banned = {"shop", "orders", "core", "cloud"}
    source_roots = (
        Path("backend/apps"),
        Path("backend/common"),
        Path("backend/config"),
        Path("backend/tests"),
    )
    paths = [path for root in source_roots for path in root.rglob("*.py")]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for item in ast.walk(tree):
            if isinstance(item, ast.Import):
                roots = [alias.name.split(".")[0] for alias in item.names]
            elif isinstance(item, ast.ImportFrom):
                roots = [(item.module or "").split(".")[0]]
            else:
                roots = []
            assert not banned.intersection(roots), str(path)


def test_archive_is_not_an_active_source_tree():
    active_roots = [
        Path("backend"),
        Path("frontend"),
        Path("installer"),
        Path("deploy"),
        Path("scripts"),
        Path("tests"),
    ]
    for root in active_roots:
        if root.exists():
            assert not any("archive" in path.parts for path in root.rglob("*"))
