"""모듈 경계 검사 — 레포 안의 모든 `app.*` import 가 이 레포 안에서 해결되어야 한다.

두 공개 모듈은 OpenSearch/Neptune 데이터로만 연결되고 코드 의존이 없다.
다른 모듈의 코드를 끌어오면 이 테스트가 깨진다.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"__pycache__", ".venv", "build", "dist"}


def _referenced_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").startswith("app"):
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            mods |= {a.name for a in node.names if a.name.startswith("app")}
    return mods


def test_no_dangling_app_imports():
    dangling = [
        f"{py.relative_to(ROOT)} → {mod}"
        for py in sorted(ROOT.rglob("*.py"))
        if not SKIP & set(py.parts)
        for mod in _referenced_modules(py)
        if not (ROOT / Path(*mod.split("."))).with_suffix(".py").exists()
        and not (ROOT / Path(*mod.split(".")) / "__init__.py").exists()
    ]
    assert not dangling, "레포 밖 모듈 참조:\n" + "\n".join(dangling)
