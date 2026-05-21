import pytest
import policy


def test_os_import_blocked():
    with pytest.raises(ValueError, match="forbidden import: os"):
        policy.check("import os")


def test_socket_import_blocked():
    with pytest.raises(ValueError, match="forbidden import: socket"):
        policy.check("import socket")


def test_subprocess_import_blocked():
    with pytest.raises(ValueError, match="forbidden import: subprocess"):
        policy.check("import subprocess")


def test_pathlib_import_blocked():
    with pytest.raises(ValueError, match="forbidden import: pathlib"):
        policy.check("from pathlib import Path")


def test_builtins_import_blocked():
    with pytest.raises(ValueError, match="forbidden import: builtins"):
        policy.check("import builtins")


def test_sys_import_blocked():
    with pytest.raises(ValueError, match="forbidden import: sys"):
        policy.check("import sys")


def test_open_call_blocked():
    with pytest.raises(ValueError, match="forbidden call: open"):
        policy.check("open('/etc/passwd')")


def test_eval_call_blocked():
    with pytest.raises(ValueError, match="forbidden call: eval"):
        policy.check("eval('1+1')")


def test_exec_call_blocked():
    with pytest.raises(ValueError, match="forbidden call: exec"):
        policy.check("exec('print(1)')")


def test_import_inside_function_blocked():
    with pytest.raises(ValueError, match="forbidden import: os"):
        policy.check("def action(state):\n    import os\n    return 'STAY'")


def test_dunder_globals_blocked():
    with pytest.raises(ValueError, match="forbidden attribute access: __globals__"):
        policy.check("def action(state):\n    return action.__globals__")


def test_forbidden_dunder_reduce_blocked():
    with pytest.raises(ValueError, match="forbidden attribute access: __reduce__"):
        policy.check("x = obj.__reduce__()")


def test_code_size_exceeded():
    big_code = "x = 1\n" * 10000
    with pytest.raises(ValueError, match="byte limit"):
        policy.check(big_code)


def test_valid_simple_code_passes():
    policy.check("def action(state): return 'STAY'")


def test_valid_complex_code_passes():
    policy.check("""
def action(state):
    tick = state.get('tick', 0)
    my_bot = state.get('my_bot', {})
    if tick % 3 == 0:
        return 'MOVE_UP'
    leaderboard = state.get('leaderboard', [])
    if len(leaderboard) > 0:
        return 'SHIELD'
    return 'STAY'
""")


def test_math_and_collections_allowed():
    policy.check("""
def action(state):
    prices = [1.0, 2.0, 3.0]
    avg = sum(prices) / len(prices)
    return 'STAY' if avg > 1.5 else 'MOVE_UP'
""")


# ── getattr / setattr / delattr / hasattr bypass prevention ──────────────────

def test_getattr_blocked():
    with pytest.raises(ValueError, match="forbidden name: getattr"):
        policy.check("getattr([], '__class__')")


def test_setattr_blocked():
    with pytest.raises(ValueError, match="forbidden name: setattr"):
        policy.check("setattr(obj, '__class__', int)")


def test_delattr_blocked():
    with pytest.raises(ValueError, match="forbidden name: delattr"):
        policy.check("delattr(obj, 'x')")


def test_hasattr_blocked():
    with pytest.raises(ValueError, match="forbidden name: hasattr"):
        policy.check("hasattr(obj, '__class__')")


def test_getattr_alias_inside_function_blocked():
    """Aliasing getattr to variable must also be rejected (not just direct calls)."""
    with pytest.raises(ValueError, match="forbidden name: getattr"):
        policy.check("""
def action(state):
    g = getattr
    return g([], '__class__')
""")


# ── Additional dunder attributes ─────────────────────────────────────────────

def test_dunder_base_blocked():
    with pytest.raises(ValueError, match="forbidden attribute access: __base__"):
        policy.check("x = int.__base__")


def test_dunder_getattribute_blocked():
    with pytest.raises(ValueError, match="forbidden attribute access: __getattribute__"):
        policy.check("x = obj.__getattribute__('x')")


def test_dunder_new_blocked():
    with pytest.raises(ValueError, match="forbidden attribute access: __new__"):
        policy.check("x = object.__new__(object)")


# ── Format-string dunder traversal bypass prevention ─────────────────────────

def test_format_string_dunder_class_blocked():
    """Classic sandbox escape via str.format() — method call is blocked."""
    with pytest.raises(ValueError, match="forbidden method call: .format()"):
        policy.check('"{0.__class__}".format([])')


def test_format_string_dunder_subclasses_blocked():
    """Deep traversal through format string fields — method call is blocked."""
    with pytest.raises(ValueError, match="forbidden method call: .format()"):
        policy.check('"{0.__class__.__bases__[0].__subclasses__()}".format([])')


def test_format_string_dunder_globals_blocked():
    with pytest.raises(ValueError, match="forbidden method call: .format()"):
        policy.check('"{0.__init__.__globals__}".format(lambda: None)')


def test_format_string_dunder_inside_function_blocked():
    """Format string escape inside an action() function."""
    with pytest.raises(ValueError, match="forbidden method call: .format()"):
        policy.check("""
def action(state):
    leak = "{0.__class__.__mro__}".format([])
    return 'STAY'
""")


def test_format_string_no_dunder_literal_allowed():
    """Normal .format() calls are blocked regardless of content (method blocked)."""
    with pytest.raises(ValueError, match="forbidden method call: .format()"):
        policy.check("""
def action(state):
    msg = "tick={0}".format(state.get('tick', 0))
    return 'STAY'
""")


def test_format_method_constructed_string_blocked():
    """Dynamically constructed template + .format() must also be rejected."""
    with pytest.raises(ValueError, match="forbidden method call: .format()"):
        policy.check("""
def action(state):
    s = "{0." + "__class__" + "}"
    return s.format([])
""")


def test_format_map_blocked():
    with pytest.raises(ValueError, match="forbidden method call: .format_map()"):
        policy.check('"{name}".format_map({"name": "x"})')


def test_fstring_allowed():
    """f-strings are fine — their expressions are full AST nodes."""
    policy.check("""
def action(state):
    tick = state.get('tick', 0)
    msg = f"tick={tick}"
    return 'STAY'
""")


# ── Bound-method alias bypass prevention ─────────────────────────────────────

def test_format_bound_method_alias_blocked():
    """Assigning .format to a variable must be rejected at attribute-access level."""
    with pytest.raises(ValueError, match="forbidden attribute access: format"):
        policy.check("""
def action(state):
    fmt = "".format
    return fmt("{0.__class__}", [])
""")


def test_str_format_classmethod_alias_blocked():
    """str.format (classmethod reference) must also be rejected."""
    with pytest.raises(ValueError, match="forbidden attribute access: format"):
        policy.check("""
def action(state):
    f = str.format
    return f("{0.__class__}", [])
""")


def test_format_map_bound_method_alias_blocked():
    with pytest.raises(ValueError, match="forbidden attribute access: format_map"):
        policy.check("""
def action(state):
    fm = {}.format_map
    return fm({"x": 1})
""")
