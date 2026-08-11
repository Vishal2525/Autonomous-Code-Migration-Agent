from pathlib import Path

from app.indexing.ast_analyzer import PythonAnalyzer, module_name_for
from app.indexing.graph import build_dependency_graph, execution_order


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "a.py").write_text(
        "import os\nimport flask\nfrom pkg.b import helper\n\n\ndef top():\n    return helper()\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "b.py").write_text(
        "from .c import value\n\n\ndef helper():\n    return value\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "c.py").write_text("value = 42\n", encoding="utf-8")
    (repo / "routes.py").write_text(
        "from flask import Blueprint\n\nbp = Blueprint('x', __name__)\n\n\n"
        "@bp.route('/invoices', methods=['GET', 'POST'])\ndef invoices():\n    return []\n\n\n"
        "@bp.get('/health')\ndef health():\n    return {'ok': True}\n",
        encoding="utf-8",
    )
    return repo


FILES = ["pkg/__init__.py", "pkg/a.py", "pkg/b.py", "pkg/c.py", "routes.py"]


def test_module_names():
    assert module_name_for("pkg/a.py") == "pkg.a"
    assert module_name_for("pkg/__init__.py") == "pkg"
    assert module_name_for("routes.py") == "routes"


def test_absolute_and_relative_import_resolution(tmp_path):
    repo = _make_repo(tmp_path)
    analyzer = PythonAnalyzer(repo, FILES)
    a = analyzer.analyze_file("pkg/a.py")
    assert "pkg/b.py" in a["local_dependencies"]
    assert "flask" in a["external_libs"]
    assert "os" not in a["external_libs"]  # stdlib is not external

    b = analyzer.analyze_file("pkg/b.py")
    assert b["local_dependencies"] == ["pkg/c.py"]


def test_route_detection(tmp_path):
    repo = _make_repo(tmp_path)
    analyzer = PythonAnalyzer(repo, FILES)
    routes = analyzer.analyze_file("routes.py")["routes"]
    by_path = {r["path"]: r for r in routes}
    assert by_path["/invoices"]["methods"] == ["GET", "POST"]
    assert by_path["/health"]["methods"] == ["GET"]
    assert by_path["/invoices"]["function"] == "invoices"


def test_symbols_extracted(tmp_path):
    repo = _make_repo(tmp_path)
    analyzer = PythonAnalyzer(repo, FILES)
    a = analyzer.analyze_file("pkg/a.py")
    assert [f["name"] for f in a["functions"]] == ["top"]


def test_dependency_graph_and_reverse(tmp_path):
    repo = _make_repo(tmp_path)
    analyzer = PythonAnalyzer(repo, FILES)
    analyses = analyzer.analyze_all()
    deps, reverse = build_dependency_graph(analyses)
    assert deps["pkg/a.py"] == ["pkg/b.py"]
    assert deps["pkg/b.py"] == ["pkg/c.py"]
    assert reverse["pkg/c.py"] == ["pkg/b.py"]
    assert reverse["pkg/b.py"] == ["pkg/a.py"]


def test_execution_order_puts_dependencies_first(tmp_path):
    repo = _make_repo(tmp_path)
    analyzer = PythonAnalyzer(repo, FILES)
    deps, _ = build_dependency_graph(analyzer.analyze_all())
    order = execution_order(deps, ["pkg/a.py", "pkg/b.py", "pkg/c.py"])
    assert order.index("pkg/c.py") < order.index("pkg/b.py") < order.index("pkg/a.py")


def test_syntax_error_is_reported_not_raised(tmp_path):
    repo = tmp_path / "repo2"
    repo.mkdir()
    (repo / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    analyzer = PythonAnalyzer(repo, ["bad.py"])
    result = analyzer.analyze_file("bad.py")
    assert result["error"] and "SyntaxError" in result["error"]
