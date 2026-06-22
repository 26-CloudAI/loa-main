"""
AST-based static policy check for user-submitted bot code.

This is a supplementary defense layer.
Primary isolation is provided by the child process, gVisor, NetworkPolicy, and resource limits.
"""

from __future__ import annotations

import ast
import os
import re

MAX_CODE_BYTES: int = int(os.environ.get("BOT_MAX_CODE_BYTES", "51200"))

_FORBIDDEN_IMPORTS = frozenset([
    "os", "sys", "socket", "subprocess", "pathlib", "builtins",
    "importlib", "ctypes", "signal", "threading", "multiprocessing",
    "pickle", "shelve", "shutil", "tempfile", "io", "fcntl",
    "pty", "nt", "posix", "resource", "gc", "inspect", "dis",
    "code", "codeop", "ast", "types", "weakref",
])

_FORBIDDEN_CALLS = frozenset([
    "open", "exec", "eval", "compile", "__import__",
    "globals", "locals", "vars", "dir", "input", "breakpoint",
])

# Names forbidden even as references (assignment, default arg, etc.) — aliasing
# any of these bypasses the call-site check above.
_FORBIDDEN_NAMES = frozenset([
    "getattr", "setattr", "delattr", "hasattr",
])

# str.format() / format_map() field syntax allows runtime attribute traversal
# via {0.__class__} — these never produce ast.Attribute nodes, bypassing AST
# checks. Block the method calls entirely so neither static nor dynamically
# constructed templates can exploit the format mini-language.
# Also scan string literals for dunder format patterns as defence-in-depth.
_FORMAT_DUNDER_RE = re.compile(r"\{[^}]*__[^}]*\}")

# str methods that allow runtime attribute/item traversal in their field syntax
_FORBIDDEN_METHODS = frozenset(["format", "format_map"])

# Dunder attributes that can be used to escape sandbox
_FORBIDDEN_DUNDERS = frozenset([
    "__builtins__", "__globals__", "__code__", "__dict__",
    "__module__", "__qualname__", "__closure__", "__func__",
    "__self__", "__wrapped__", "__subclasses__", "__bases__",
    "__mro__", "__init_subclass__", "__class_getitem__",
    "__reduce__", "__reduce_ex__", "__getstate__", "__setstate__",
    # Singular base + descriptor/slot protocol dunders
    "__base__", "__getattr__", "__getattribute__", "__setattr__",
    "__delattr__", "__get__", "__set__", "__delete__", "__new__",
    # Traceback object exposes the live frame chain → builtins/globals recovery
    "__traceback__",
])

# Traceback/frame attributes (non-dunder, so not covered above). Walking the
# frame chain via e.__traceback__.tb_frame.f_back.f_builtins['__import__']
# recovers full builtins/imports despite SAFE_BUILTINS and forbidden-import
# checks. Block every step of that chain.
_FORBIDDEN_FRAME_ATTRS = frozenset([
    "tb_frame", "tb_next", "tb_lineno", "tb_lasti",
    "f_back", "f_builtins", "f_globals", "f_locals",
    "f_code", "f_lineno", "f_trace",
])


def check(code: str) -> None:
    """Raise ValueError if code violates security policy."""
    if len(code.encode()) > MAX_CODE_BYTES:
        raise ValueError(f"code exceeds {MAX_CODE_BYTES} byte limit")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"syntax error: {exc}") from exc

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _FORBIDDEN_IMPORTS:
                    raise ValueError(f"forbidden import: {top}")

        elif isinstance(node, ast.ImportFrom):
            top = (node.module or "").split(".")[0]
            if top in _FORBIDDEN_IMPORTS:
                raise ValueError(f"forbidden import: {top}")

        elif isinstance(node, ast.Name):
            # Block forbidden names even when referenced (not called) — prevents aliasing.
            if node.id in _FORBIDDEN_NAMES:
                raise ValueError(f"forbidden name: {node.id}")

        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _FORBIDDEN_CALLS:
                raise ValueError(f"forbidden call: {node.func.id}")
            # Block str.format() / str.format_map() — the format mini-language
            # performs runtime attribute traversal that AST checks cannot see,
            # even when the template string is built dynamically at runtime.
            if isinstance(node.func, ast.Attribute) and node.func.attr in _FORBIDDEN_METHODS:
                raise ValueError(f"forbidden method call: .{node.func.attr}()")

        elif isinstance(node, ast.Attribute):
            # _FORBIDDEN_METHODS checked here (not just at ast.Call) so that
            # bound-method aliases like `fmt = "".format` are also rejected.
            if (node.attr in _FORBIDDEN_DUNDERS
                    or node.attr in _FORBIDDEN_METHODS
                    or node.attr in _FORBIDDEN_FRAME_ATTRS):
                raise ValueError(f"forbidden attribute access: {node.attr}")

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Catch dunder traversal embedded in format-string literals:
            # "{0.__class__.__bases__[0].__subclasses__()}".format([])
            # These produce no ast.Attribute nodes, bypassing the check above.
            if _FORMAT_DUNDER_RE.search(node.value):
                raise ValueError("forbidden format string: dunder access via str.format()")
