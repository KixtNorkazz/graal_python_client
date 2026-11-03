"""Compile a script expression (GS1 text from the server or a level file) for eval() without letting it reach Python itself.

- No attribute access: `().__class__.__base__.__subclasses__()` is how an expression escapes an empty __builtins__.
- No bit shifts: `1 << 99999999999` allocates without bound (GS1 has no shift operators).
- `**` and `*` are computed on floats (`_pow_`, `_mul_`): `9 ** 9 ** 8` on Python ints runs for minutes and `"x" * 10 ** 9`
  allocates a gigabyte; GS1 only has numeric `^` and `*`, so the result is the same for real scripts.
Callers add ARITH (or their own `_pow_` / `_mul_` taking their value types) to the eval environment.
"""
import ast, math


def _f(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0


def safe_pow(a, b):
    try: return math.pow(a, b)
    except (OverflowError, ValueError, ZeroDivisionError): return 0.0


def safe_mul(a, b):
    v = a * b
    return v if math.isfinite(v) else 0.0


ARITH = {"_pow_": lambda a, b: safe_pow(_f(a), _f(b)), "_mul_": lambda a, b: safe_mul(_f(a), _f(b))}


class _Rewrite(ast.NodeTransformer):
    def visit_BinOp(self, node):
        self.generic_visit(node)
        name = {ast.Pow: "_pow_", ast.Mult: "_mul_"}.get(type(node.op))
        if name is None: return node
        return ast.copy_location(ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[node.left, node.right], keywords=[]), node)


def compile_expr(text, filename="<gs1>"):
    """A code object for eval(), or None when the expression is not allowed (or not valid)."""
    try: tree = ast.parse(text.strip(), filename, "eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError): return None
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute): return None
        if isinstance(n, (ast.BinOp, ast.AugAssign)) and isinstance(n.op, (ast.LShift, ast.RShift)): return None
        if isinstance(n, ast.Name) and n.id.startswith("__"): return None
    try: return compile(ast.fix_missing_locations(_Rewrite().visit(tree)), filename, "eval")
    except (SyntaxError, ValueError, RecursionError): return None
