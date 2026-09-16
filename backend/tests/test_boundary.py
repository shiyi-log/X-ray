import ast
from pathlib import Path


def test_no_shop_imports():
    banned = {"shop", "orders", "core", "cloud"}
    for path in Path("backend").rglob("*.py"):
        if "archive" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for item in ast.walk(tree):
            roots = ([alias.name.split(".")[0] for alias in item.names] if isinstance(item, ast.Import) else [(item.module or "").split(".")[0]] if isinstance(item, ast.ImportFrom) else [])
            assert not banned.intersection(roots), str(path)
