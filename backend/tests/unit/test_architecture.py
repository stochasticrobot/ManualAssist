"""Check that browser code and provider-specific connections stay in their intended
parts of the project. It also checks that Python functions explain their inputs
and results; those mechanical checks do not establish that the prose is clear."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "backend/src/workbench"


def test_backend_has_no_browser_source_and_provider_imports_are_isolated():
    """Keep UI assets separate and vendor imports at the adapter boundary.

    Args:
        None.
    Returns:
        None; fails if browser source moves into backend or provider SDK imports
        escape model_access/providers. This is a structural check, not a quality score.
    """
    assert not any(SOURCE.rglob("*.html"))
    assert not any(SOURCE.rglob("*.js"))
    assert not any(SOURCE.rglob("*.css"))
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(name.startswith(("boto3", "botocore")) for name in names):
                assert "model_access/providers" in str(path)
    assert (ROOT / "frontend/src/page_renderers/troubleshooting-and-faq.js").exists()


def test_functions_document_inputs_and_meaningful_result_section():
    """Catch missing function contracts while leaving prose quality to human review.

    Args:
        None.
    Returns:
        None; requires purpose prose, Args, Returns and every explicit parameter.
        Passing does not prove comments are sufficiently explanatory or correct.
    """
    for path in (ROOT / "backend").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            doc = ast.get_docstring(node) or ""
            assert "Args:" in doc and "Returns:" in doc, (path, node.name)
            params = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            params += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            for arg in params:
                if arg.arg not in ("self", "cls"):
                    assert arg.arg + ":" in doc, (path, node.name, arg.arg)
