"""GS2 source interpreter (client side): lexer, parser and a generator-based evaluator.

GS2 scripts reach us as source text (the server only sends bytecode in `generation=modern` mode), so this runs them directly.
Scope: what the RP server scripts use: `function name(params) {}`, if/else/for/while/foreach/switch/with, `temp.` / `this.` / `client.`
variables, bare NPC properties (x, y, image, ...), arrays `{a, b}`, `in |lo,hi|`, string operators `@ SPC NL TAB`, `sleep()`,
`setTimer()`, `scheduleevent()`, `join("class")`. Everything that is not a language builtin is passed to the host (`host.call`),
which bridges to the GS1 command implementations. Not covered: classes/`new`, `with` on arbitrary objects beyond images/NPC,
return values from functions that `sleep`, particle emitters (`addlocalmodifier`)."""
import math, random, re, time
from gs2sched import Wait

class Gs2Error(Exception): pass

import os
SANDBOX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server_files")   # in the project folder

def sandbox_path(name, create=False):
    """Map a script file name into the sandbox: no absolute paths, no `..`, no escaping through links."""
    rel = text(name).replace("\\", "/").lstrip("/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts): return None
    path = os.path.join(SANDBOX, *parts)
    if create: os.makedirs(os.path.dirname(path), exist_ok=True)
    return path if os.path.realpath(path).startswith(os.path.realpath(SANDBOX) + os.sep) or not os.path.exists(path) else None

SANDBOX_MAX_FILE = 1 << 20; SANDBOX_MAX_FILES = 256   # savestring/savelines come from server scripts: they must not fill the disk

def sandbox_write(path, data):
    """Write a script's file inside the sandbox, within the size and file-count limits; False when refused."""
    if len(data) > SANDBOX_MAX_FILE: return False
    if not os.path.exists(path) and sum(len(f) for _, _, f in os.walk(SANDBOX)) >= SANDBOX_MAX_FILES: return False
    with open(path, "w", encoding="latin1") as f: f.write(data)
    return True

_TOK = re.compile(r"""
    (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<num>\d+\.\d+|\d+|\.\d+)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<id>[A-Za-z_]\w*)
  | (?P<op>==|!=|<=|>=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|%=|@=|[-+*/%<>=!@(){}\[\],;.:?|^])
""", re.X | re.S)

def lex(src):
    out, i = [], 0
    while i < len(src):
        m = _TOK.match(src, i)
        if not m: i += 1; continue
        i = m.end(); k = m.lastgroup
        if k == "ws": continue
        t = m.group(k)
        if k == "num": out.append(("num", float(t)))
        elif k == "str": out.append(("str", re.sub(r"\\(.)", lambda mm: {"n": "\n", "t": "\t"}.get(mm.group(1), mm.group(1)), t[1:-1])))
        elif k == "id": out.append(("id", t))
        else: out.append(("op", t))
    return out

_CONCAT = {"@": "", "SPC": " ", "NL": "\n", "TAB": "\t"}

class Parser:
    def __init__(self, toks): self.t, self.i = toks, 0
    def peek(self, k=0): return self.t[self.i + k] if self.i + k < len(self.t) else ("eof", None)
    def next(self): tok = self.peek(); self.i += 1; return tok
    def is_op(self, v, k=0): t = self.peek(k); return t[0] == "op" and t[1] == v
    def is_id(self, v, k=0): t = self.peek(k); return t[0] == "id" and t[1].lower() == v
    def eat_op(self, v):
        if self.is_op(v): self.i += 1; return True
        return False
    def expect(self, v):
        if not self.eat_op(v): raise Gs2Error(f"expected {v!r}, got {self.peek()!r}")

    def program(self):
        out = []
        while self.peek()[0] != "eof":
            n = self.stmt()
            if n: out.append(n)
        return out

    def block(self):
        self.expect("{"); out = []
        while not self.is_op("}"):
            if self.peek()[0] == "eof": raise Gs2Error("unterminated block")
            n = self.stmt()
            if n: out.append(n)
        self.expect("}"); return ("block", out)

    def stmt(self):
        if self.eat_op(";"): return None
        if self.is_op("{"): return self.block()
        t = self.peek()
        if t[0] == "id":
            w = t[1].lower()
            if w == "public" and self.is_id("function", 1): self.i += 1; w = "function"
            if w == "function" and self.peek(1)[0] == "id":
                self.i += 1; name = self.next()[1]
                while self.is_op(".") and self.peek(1)[0] == "id": self.i += 1; name += "." + self.next()[1]
                self.expect("("); params = []
                while not self.is_op(")"):
                    tok = self.next()
                    if tok[0] == "id": params.append(tok[1])
                    self.eat_op(",")
                self.expect(")"); body = self.stmt() or ("block", [])
                return ("func", name.lower(), params, body)
            if w == "if":
                self.i += 1; self.expect("("); c = self.expr(); self.expect(")"); a = self.stmt() or ("block", []); b = None
                if self.is_id("else"): self.i += 1; b = self.stmt() or ("block", [])
                return ("if", c, a, b)
            if w == "while":
                self.i += 1; self.expect("("); c = self.expr(); self.expect(")"); return ("while", c, self.stmt() or ("block", []))
            if w == "for":
                self.i += 1; self.expect("("); start = self.i
                try: var = self.expr()
                except Gs2Error: var = None
                if var is not None and self.eat_op(":"):
                    coll = self.expr(); self.expect(")"); return ("foreach", var, coll, self.stmt() or ("block", []))
                self.i = start; init = self.expr_list(";"); self.expect(";"); c = self.expr() if not self.is_op(";") else ("num", 1.0)
                self.expect(";"); step = self.expr_list(")"); self.expect(")"); return ("for", init, c, step, self.stmt() or ("block", []))
            if w == "foreach":
                self.i += 1; self.expect("("); var = self.expr()
                if not (self.eat_op(":") or (self.is_id("in") and self.next())): raise Gs2Error("foreach needs ':'")
                coll = self.expr(); self.expect(")"); return ("foreach", var, coll, self.stmt() or ("block", []))
            if w == "with":
                self.i += 1; self.expect("("); o = self.expr(); self.expect(")"); return ("with", o, self.stmt() or ("block", []))
            if w == "switch":
                self.i += 1; self.expect("("); v = self.expr(); self.expect(")"); self.expect("{"); cases = []
                while not self.is_op("}"):
                    if self.is_id("case"): self.i += 1; label = self.expr(); self.expect(":")
                    elif self.is_id("default"): self.i += 1; self.expect(":"); label = None
                    else: raise Gs2Error("bad switch")
                    body = []
                    while not (self.is_op("}") or self.is_id("case") or self.is_id("default")):
                        n = self.stmt()
                        if n: body.append(n)
                    cases.append((label, body))
                self.expect("}"); return ("switch", v, cases)
            if w == "enum" and (self.is_op("{", 1) or (self.peek(1)[0] == "id" and self.is_op("{", 2))):
                self.i += 1
                if self.peek()[0] == "id": self.i += 1
                self.expect("{"); items = []
                while not self.is_op("}"):
                    t = self.next()
                    if t[0] != "id": raise Gs2Error("bad enum")
                    val = self.expr() if self.eat_op("=") else None
                    items.append((t[1], val)); self.eat_op(",")
                self.expect("}"); self.eat_op(";"); return ("enum", items)
            if w in ("break", "continue"): self.i += 1; self.eat_op(";"); return (w,)
            if w == "return":
                self.i += 1; v = None if (self.is_op(";") or self.is_op("}")) else self.expr(); self.eat_op(";"); return ("return", v)
        e = self.expr_list(";"); self.eat_op(";")
        return ("expr", e)

    def expr_list(self, stop):
        items = []
        if self.is_op(stop): return ("seq", items)
        items.append(self.expr())
        while self.eat_op(","): items.append(self.expr())
        return ("seq", items)

    def expr(self): return self.assign()

    def assign(self):
        lhs = self.ternary()
        t = self.peek()
        if t[0] == "op" and t[1] in ("=", "+=", "-=", "*=", "/=", "%=", "@="):
            self.i += 1; return ("assign", t[1], lhs, self.assign())
        return lhs

    def ternary(self):
        c = self.binary(0)
        if self.eat_op("?"):
            a = self.assign(); self.expect(":"); return ("cond", c, a, self.assign())
        return c

    LEVELS = [("||",), ("&&",), ("in",), ("==", "!="), ("<", ">", "<=", ">="), ("@", "SPC", "NL", "TAB"), ("+", "-"), ("*", "/", "%"), ("^",)]
    def binary(self, lv):
        if lv >= len(self.LEVELS): return self.unary()
        left = self.binary(lv + 1); ops = self.LEVELS[lv]
        while True:
            t = self.peek(); v = t[1]
            if t[0] == "op" and v in ops or (t[0] == "id" and v in ops and v != "in") or (t[0] == "id" and v == "in" and "in" in ops):
                self.i += 1
                if v == "in" and self.is_op("|"):
                    self.i += 1; lo = self.expr(); self.expect(","); hi = self.expr(); self.expect("|"); left = ("inrange", left, lo, hi); continue
                left = ("bin", v, left, self.binary(lv + 1))
            else: return left

    def unary(self):
        t = self.peek()
        if t[0] == "op" and t[1] in ("!", "-", "+"): self.i += 1; return ("un", t[1], self.unary())
        if t[0] == "op" and t[1] in ("++", "--"): self.i += 1; target = self.unary(); return ("assign", "+=" if t[1] == "++" else "-=", target, ("num", 1.0))
        return self.postfix()

    def postfix(self):
        e = self.primary()
        while True:
            if self.eat_op("("):
                args = []
                while not self.is_op(")"):
                    args.append(self.expr())
                    if not self.eat_op(","): break
                self.expect(")"); e = ("call", e, args)
            elif self.eat_op("."):
                if self.is_op("(") and self.is_op("@", 1):
                    self.i += 2; ne = self.expr(); self.expect(")"); e = ("dynmember", e, ne); continue
                t = self.next()
                if t[0] != "id": raise Gs2Error("bad member")
                e = ("member", e, t[1])
            elif self.eat_op("["):
                i = self.expr(); self.expect("]"); e = ("index", e, i)
            elif self.is_op("++") or self.is_op("--"):
                op = self.next()[1]; e = ("postinc", "+=" if op == "++" else "-=", e)
            else: return e

    def primary(self):
        t = self.next()
        if t[0] == "num": return ("num", t[1])
        if t[0] == "str": return ("str", t[1])
        if t[0] == "id":
            w = t[1]
            if w.lower() == "true": return ("num", 1.0)
            if w.lower() == "false": return ("num", 0.0)
            if w.lower() in ("null", "none"): return ("null",)
            if w.lower() == "pi": return ("num", math.pi)
            if w.lower() == "new":
                if self.eat_op("["): n = self.expr(); self.expect("]"); return ("newarr", n)
                cls = self.next()[1] if self.peek()[0] == "id" else ""; args = []
                if self.eat_op("("):
                    while not self.is_op(")"):
                        args.append(self.expr())
                        if not self.eat_op(","): break
                    self.expect(")")
                body = self.block() if self.is_op("{") else None
                return ("newobj", cls, args, body)
            return ("name", w)
        if t[0] == "op" and t[1] == "(":
            if self.eat_op("@"): e = self.expr(); self.expect(")"); return ("dyn", e)
            e = self.expr(); self.expect(")"); return e
        if t[0] == "op" and t[1] == "{":
            items = []
            while not self.is_op("}"):
                items.append(self.expr())
                if not self.eat_op(","): break
            self.expect("}"); return ("array", items)
        raise Gs2Error(f"unexpected {t!r}")

def parse(src): return Parser(lex(src)).program()

def truth(v):
    if v is None: return False
    if isinstance(v, str): return v != "" and v.lower() != "false" and v != "0"
    if isinstance(v, (list, dict)): return len(v) > 0
    return bool(v)

def num(v):
    if isinstance(v, bool): return 1.0 if v else 0.0
    if isinstance(v, (int, float)): return float(v)
    if isinstance(v, str):
        m = re.match(r"\s*-?(\d+\.?\d*|\.\d+)", v)
        return float(m.group(0)) if m else 0.0
    return 0.0

def text(v):
    if v is None: return ""
    if isinstance(v, Obj):
        for k in ("name", "account"):
            n = v.get(k)
            if n: return str(n)
        return ""
    if isinstance(v, float): return str(int(v)) if v == int(v) else f"{v:.5f}".rstrip("0").rstrip(".")
    if isinstance(v, bool): return "1" if v else "0"
    if isinstance(v, list): return ",".join(text(x) for x in v)
    return str(v)

def equal(a, b):
    if isinstance(a, (Obj, list)) or isinstance(b, (Obj, list)): return a is b
    if isinstance(a, str) or isinstance(b, str):
        if isinstance(a, str) and isinstance(b, str): return a.lower() == b.lower()
        s, o = (a, b) if isinstance(a, str) else (b, a)
        if isinstance(o, (int, float)) and re.fullmatch(r"\s*-?(\d+\.?\d*|\.\d+)\s*", s): return num(s) == num(o)
        return text(a).lower() == text(b).lower()
    return num(a) == num(b)

class Obj:
    """Script-visible object: attribute get/set and method calls (host objects subclass this)."""
    objtype = "Object"
    def has(self, name): return False
    def get(self, name): return None
    def set(self, name, value): pass
    def call(self, name, args): return None
    def varnames(self, kind): return []
    def funcnames(self): return []

def introspect(o, name, args):
    """Methods every script object has: type(), objectType(), getVarNames() and friends, getFunctions()."""
    if name == "type": return 2.0
    if name == "objecttype": return o.objtype
    if name == "getvarnames": return o.varnames("all")
    if name in ("getstaticvarnames", "getdynamicvarnames", "geteditvarnames"): return o.varnames(name[3:-8])
    if name == "getfunctions": return o.funcnames()
    return None

class DictObj(Obj):
    def __init__(self, d=None): self.d = {} if d is None else d
    objtype = "TGraalVar"
    def has(self, name): return name.lower() in self.d
    def get(self, name): return self.d.get(name.lower())
    def set(self, name, value): self.d[name.lower()] = value
    def varnames(self, kind): return list(self.d) if kind in ("all", "dynamic") else []

class NullObj(Obj):
    """Placeholder for objects we do not model (GUI controls, emitters): swallows everything."""
    def has(self, name): return True

def _drop(stack, item):
    """Pop `item` from a frame / with stack. A suspended coroutine that is garbage collected unwinds after other coroutines swapped the
    stacks, so the item may be gone or not on top."""
    if stack and stack[-1] is item: stack.pop()
    elif item in stack: stack.remove(item)

class _Return(Exception):
    def __init__(self, v): self.v = v
class _Break(Exception): pass
class _Continue(Exception): pass

MAX_STEPS = 400_000
WAITERS = set()

class Interp:
    """One script instance. `host` provides: props (get_prop/set_prop/has_prop), call(name, args) for commands, globals_obj(name)."""
    def __init__(self, host, src, class_loader=None, this=None):
        self.host = host; self.params = []; self._ng = {}; self.funcs = {}; self.class_loader = class_loader; self.steps = 0; self.joined = set()
        self.consts = {}; self.this = this if this is not None else ThisObj(self); self.frames = []; self.withs = []
        self.load(src)

    def load(self, src):
        self._ng = {}; self._ng_dirty = True
        for n in parse(src):
            if n[0] == "func": self.funcs.setdefault(n[1], []).append(n)
        self._register_waiters()
        self.top = [n for n in parse(src) if n[0] not in ("func",)]
        for n in self.top:
            if n[0] == "enum":
                for _ in self.exec(n): pass

    def _register_waiters(self):
        def calls_wait(n):
            if not isinstance(n, tuple): return False
            if n and n[0] == "call" and n[1][0] == "name" and (n[1][1].lower() == "waitfor" or n[1][1].lower() in WAITERS): return True
            if n and n[0] == "call" and n[1][0] == "member" and n[1][2].lower() in WAITERS: return True
            for x in n:
                if isinstance(x, tuple) and calls_wait(x): return True
                if isinstance(x, list) and any(isinstance(y, tuple) and calls_wait(y) for y in x): return True
            return False
        for _ in range(3):
            for name, defs in self.funcs.items():
                if name not in WAITERS and any(calls_wait(d[3]) for d in defs): WAITERS.add(name.split(".")[-1])

    def has_function(self, name): return name.lower() in self.funcs

    def fire_trigger(self, this, name, args):
        """trigger("Name", arg): run onName(arg) in this script and wake waitfor(this, "Name", ...) callers."""
        for f in list(self.funcs.get("on" + name.lower(), [])): self.call_sync(f, list(args))
        wake = getattr(self.host, "wake", None)
        if wake: wake(getattr(this, "name", None) or "", name)

    def call_function(self, name, args=()):
        """Run all definitions of `name` (a joined class adds its own); a generator that yields sleep delays (and Waits).
        Each call chain owns its frame / with stacks: they are swapped in on every resume, so interleaved coroutines do not corrupt each other."""
        self.steps = 0; self.params = list(args)
        fr, wi = [], []; inner = self._call_all(name, args)
        self.frames, self.withs = fr, wi
        try:
            d = next(inner)
            while True:
                sent = yield d
                self.frames, self.withs = fr, wi
                d = inner.send(sent)
        except StopIteration: return

    def _call_all(self, name, args):
        for f in list(self.funcs.get(name.lower(), [])): yield from self._run_func(f, list(args))

    def _run_func(self, f, args):
        return (yield from self.call_gen(f, args))

    def call_gen(self, f, args):
        """Run one function definition as a coroutine and return its value."""
        _, _, params, body = f; frame = DictObj({p.lower(): (args[k] if k < len(args) else None) for k, p in enumerate(params)})
        frame.wbase = len(self.withs); self.frames.append(frame); val = None
        try: yield from self.exec(body)
        except _Return as r: val = r.v
        except (_Break, _Continue): pass
        finally: _drop(self.frames, frame)
        return val

    def call_sync(self, f, args):
        """Function call inside an expression that cannot suspend: run to completion (sleeps / waits are skipped), return its value."""
        _, _, params, body = f; frame = DictObj({p.lower(): (args[k] if k < len(args) else None) for k, p in enumerate(params)})
        frame.wbase = len(self.withs); self.frames.append(frame); val = None
        try:
            for _ in self.exec(body): pass
        except _Return as r: val = r.v
        except (_Break, _Continue): pass
        finally: _drop(self.frames, frame)
        return val

    def tick(self):
        self.steps += 1
        if self.steps > MAX_STEPS: raise Gs2Error("step limit")

    def exec(self, n):
        self.tick(); k = n[0]
        if k == "block":
            for s in n[1]: yield from self.exec(s)
        elif k == "expr":
            for e in n[1][1]:
                if e[0] == "call" and e[1][0] == "name" and e[1][1].lower() == "sleep":
                    yield num(self.ev(e[2][0])) if e[2] else 0.0; continue
                yield from self.evg(e)
        elif k == "if":
            if truth((yield from self.evg(n[1]))): yield from self.exec(n[2])
            elif n[3]: yield from self.exec(n[3])
        elif k == "while":
            while truth((yield from self.evg(n[1]))):
                try: yield from self.exec(n[2])
                except _Break: break
                except _Continue: pass
                self.tick()
        elif k == "for":
            for e in n[1][1]: yield from self.evg(e)
            while truth((yield from self.evg(n[2]))):
                try: yield from self.exec(n[4])
                except _Break: break
                except _Continue: pass
                for e in n[3][1]: yield from self.evg(e)
                self.tick()
        elif k == "foreach":
            coll = yield from self.evg(n[2])
            for item in list(coll if isinstance(coll, list) else []):
                self.assign_to(n[1], item)
                try: yield from self.exec(n[3])
                except _Break: break
                except _Continue: pass
        elif k == "with":
            o = yield from self.evg(n[1]); self.withs.append(o)
            try: yield from self.exec(n[2])
            finally: _drop(self.withs, o)
        elif k == "switch":
            v = yield from self.evg(n[1]); hit = False
            try:
                for label, body in n[2]:
                    if not hit and (label is None or equal(v, self.ev(label))): hit = True
                    if hit:
                        for s in body: yield from self.exec(s)
            except _Break: pass
        elif k == "break": raise _Break()
        elif k == "continue": raise _Continue()
        elif k == "return": raise _Return((yield from self.evg(n[1])) if n[1] else None)
        elif k == "enum":
            nxt = 0.0
            for name, val in n[1]:
                if val is not None: nxt = num(self.ev(val))
                self.consts[name.lower()] = nxt; nxt += 1.0
        elif k == "func": pass

    def active_withs(self):
        """with-objects of the running function only: `this` and bare names are lexically scoped, while the full self.withs stack stays
        visible to the host (triggerclient targets the player of the innermost with(), however deep the call is)."""
        b = getattr(self.frames[-1], "wbase", 0) if self.frames else 0
        return self.withs[b:]

    def needs_gen(self, n):
        key = id(n); c = self._ng.get(key)
        if c is not None and c[0] == len(self.funcs): return c[1]
        r = self._scan(n); self._ng[key] = (len(self.funcs), r); return r

    def _scan(self, n):
        if not isinstance(n, tuple): return False
        if n and n[0] == "call" and n[1][0] == "name" and n[1][1].lower() in self.funcs: return True
        if n and n[0] == "call" and n[1][0] == "name" and n[1][1].lower() in ("waitfor", "trigger"): return True
        if n and n[0] == "call" and n[1][0] == "name" and n[1][1].lower() in WAITERS: return True
        if n and n[0] == "call" and n[1][0] == "member" and n[1][2].lower() in WAITERS: return True
        if n and n[0] == "newobj": return False
        for x in n:
            if isinstance(x, tuple) and self._scan(x): return True
            if isinstance(x, list):
                for y in x:
                    if isinstance(y, tuple) and self._scan(y): return True
        return False

    def evg(self, n):
        """Like ev(), but user functions run as coroutines (they may sleep / waitfor) and waitfor() suspends."""
        if not self.needs_gen(n): return self.ev(n)
        self.tick(); k = n[0]
        if k == "call":
            fn = n[1]; args = []
            for a in n[2]: args.append((yield from self.evg(a)))
            if fn[0] == "name":
                low = fn[1].lower()
                if low == "waitfor":
                    tgt = args[0] if args else ""
                    tgt = getattr(tgt, "name", None) if isinstance(tgt, Obj) and hasattr(tgt, "name") else text(tgt)
                    res = yield Wait(text(tgt), text(args[1]) if len(args) > 1 else "", num(args[2]) if len(args) > 2 else 0.0)
                    return 1.0 if res else 0.0
                if low == "trigger" and args:
                    for f in list(self.funcs.get("on" + text(args[0]).lower(), [])): yield from self.call_gen(f, args[1:])
                    wake = getattr(self.host, "wake", None)
                    if wake: wake(getattr(self.this, "name", None) or "", text(args[0]))
                    return None
                if low in self.funcs:
                    val = None
                    for f in list(self.funcs[low]): val = yield from self.call_gen(f, args)
                    return val
                if low == "sleep": yield num(args[0]) if args else 0.0; return None
            elif fn[0] == "member":
                o = self.ev(fn[1]); nm = fn[2].lower()
                if isinstance(o, ThisObj) and nm in o.interp.funcs:
                    val = None
                    for f in list(o.interp.funcs[nm]): val = yield from o.interp.call_gen(f, args)
                    return val
            return self.call_with(fn, args)
        if k == "assign":
            v = yield from self.evg(n[3])
            if n[1] != "=":
                cur = self.ev(n[2]); op = n[1][0]; v = text(cur) + text(v) if op == "@" else self.arith(op, cur, v)
            self.assign_to(n[2], v); return v
        if k == "bin":
            op = n[1]; a = yield from self.evg(n[2])
            if op == "&&": return 1.0 if truth(a) and truth((yield from self.evg(n[3]))) else 0.0
            if op == "||": return 1.0 if truth(a) or truth((yield from self.evg(n[3]))) else 0.0
            b = yield from self.evg(n[3]); return self.binop_values(op, a, b)
        if k == "un":
            v = yield from self.evg(n[2]); return (0.0 if truth(v) else 1.0) if n[1] == "!" else (-num(v) if n[1] == "-" else num(v))
        if k == "cond":
            return (yield from self.evg(n[2])) if truth((yield from self.evg(n[1]))) else (yield from self.evg(n[3]))
        if k == "seq":
            v = None
            for e in n[1]: v = yield from self.evg(e)
            return v
        if k == "array":
            out = []
            for e in n[1]: out.append((yield from self.evg(e)))
            return out
        if k == "index":
            o = yield from self.evg(n[1]); i = yield from self.evg(n[2]); return self.index_values(o, i)
        if k == "member":
            o = yield from self.evg(n[1]); return self.get_attr(o, n[2])
        return self.ev(n)

    def ev(self, n):
        self.tick(); k = n[0]
        if k == "num": return n[1]
        if k == "str": return n[1]
        if k == "null": return None
        if k == "array": return [self.ev(e) for e in n[1]]
        if k == "newarr": return [0.0] * max(0, min(10000, int(num(self.ev(n[1])))))
        if k == "newobj":
            args = [self.ev(a) for a in n[2]]; aw = self.active_withs(); parent = aw[-1] if aw and isinstance(aw[-1], Obj) else None
            obj = self.host.create_object(n[1], args, parent) if hasattr(self.host, "create_object") else None
            if obj is None: return NullObj()
            if n[3]:
                self.withs.append(obj)
                try:
                    for _ in self.exec(n[3]): pass
                finally: self.withs.pop()
            return obj
        if k == "dyn": return self.read_name(text(self.ev(n[1])))
        if k == "dynmember": return self.get_attr(self.ev(n[1]), text(self.ev(n[2])))
        if k == "name": return self.read_name(n[1])
        if k == "member":
            o = self.ev(n[1]); return self.get_attr(o, n[2])
        if k == "index": return self.index_values(self.ev(n[1]), self.ev(n[2]))
        if k == "un":
            v = self.ev(n[2])
            return (0.0 if truth(v) else 1.0) if n[1] == "!" else (-num(v) if n[1] == "-" else num(v))
        if k == "cond": return self.ev(n[2]) if truth(self.ev(n[1])) else self.ev(n[3])
        if k == "inrange": v = num(self.ev(n[1])); return 1.0 if num(self.ev(n[2])) <= v <= num(self.ev(n[3])) else 0.0
        if k == "bin": return self.binop(n)
        if k == "assign":
            v = self.ev(n[3])
            if n[1] != "=":
                cur = self.ev(n[2]); op = n[1][0]
                v = text(cur) + text(v) if op == "@" else self.arith(op, cur, v)
            self.assign_to(n[2], v); return v
        if k == "postinc":
            cur = self.ev(n[2]); self.assign_to(n[2], self.arith(n[1][0], cur, 1.0)); return cur
        if k == "call": return self.do_call(n)
        if k == "seq":
            v = None
            for e in n[1]: v = self.ev(e)
            return v
        raise Gs2Error(f"cannot evaluate {k}")

    def index_values(self, o, i):
        if isinstance(o, list):
            i = int(num(i)); return o[i] if 0 <= i < len(o) else None
        if isinstance(o, str):
            i = int(num(i)); return o[i] if 0 <= i < len(o) else ""
        if isinstance(o, Obj): return o.get(text(i))
        return None

    def arith(self, op, a, b):
        a, b = num(a), num(b)
        if op == "+": return a + b
        if op == "-": return a - b
        if op == "*": return a * b
        if op == "/": return a / b if b else 0.0
        if op == "%": return math.fmod(a, b) if b else 0.0
        if op == "^": return a ** b if abs(b) < 64 else 0.0
        return 0.0

    def binop(self, n):
        op = n[1]
        if op == "&&": return 1.0 if truth(self.ev(n[2])) and truth(self.ev(n[3])) else 0.0
        if op == "||": return 1.0 if truth(self.ev(n[2])) or truth(self.ev(n[3])) else 0.0
        return self.binop_values(op, self.ev(n[2]), self.ev(n[3]))

    def binop_values(self, op, a, b):
        if op == "==": return 1.0 if equal(a, b) else 0.0
        if op == "!=": return 0.0 if equal(a, b) else 1.0
        if op in ("<", ">", "<=", ">="):
            x, y = (text(a).lower(), text(b).lower()) if isinstance(a, str) and isinstance(b, str) else (num(a), num(b))
            return 1.0 if {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op] else 0.0
        if op in _CONCAT: return text(a) + _CONCAT[op] + text(b)
        if op == "in":
            if isinstance(b, list): return 1.0 if any(equal(a, x) for x in b) else 0.0
            return 1.0 if text(a).lower() in text(b).lower() else 0.0
        return self.arith(op, a, b)

    def read_name(self, name):
        low = name.lower()
        for o in reversed(self.active_withs()):
            if isinstance(o, Obj) and o.has(low): return o.get(low)
        if self.frames and low in self.frames[-1].d: return self.frames[-1].d[low]
        if low == "params" and not (self.frames and "params" in self.frames[-1].d): return self.params
        aw = self.active_withs()
        if low == "this": return aw[-1] if aw and isinstance(aw[-1], Obj) else self.this
        if low == "temp": return self.frames[-1] if self.frames else self.temp_global
        g = self.host.global_obj(low)
        if g is not None: return g
        if self.host.has_prop(low): return self.host.get_prop(low)
        if low in self.consts: return self.consts[low]
        if low in self.funcs: return self.call_sync(self.funcs[low][0], [])
        return self.this.get(low) if isinstance(self.this, Obj) else None

    @property
    def temp_global(self):
        if not hasattr(self, "_tg"): self._tg = DictObj()
        return self._tg

    def get_attr(self, o, name):
        low = name.lower()
        if isinstance(o, Obj): return o.get(low)
        if isinstance(o, list) and low in ("size", "length"): return float(len(o))
        if isinstance(o, str) and low == "length": return float(len(o))
        return None

    def assign_to(self, target, v):
        k = target[0]
        if k == "dyn": return self.assign_to(("name", text(self.ev(target[1]))), v)
        if k == "dynmember": return self.assign_to(("member", target[1], text(self.ev(target[2]))), v)
        if k == "name":
            low = target[1].lower()
            for o in reversed(self.active_withs()):
                if isinstance(o, Obj) and o.has(low): o.set(low, v); return
            if self.frames and low in self.frames[-1].d: self.frames[-1].d[low] = v; return
            if self.host.has_prop(low): self.host.set_prop(low, v); return
            if isinstance(self.this, Obj): self.this.set(low, v)
            else: (self.frames[-1] if self.frames else self.temp_global).d[low] = v
        elif k == "member":
            o = self.ev(target[1])
            if isinstance(o, Obj): o.set(target[2].lower(), v)
        elif k == "index":
            o = self.ev(target[1]); i = self.ev(target[2])
            if isinstance(o, list):
                i = int(num(i))
                if 0 <= i < 1000:
                    while len(o) <= i: o.append(0.0)
                    o[i] = v
            elif isinstance(o, Obj): o.set(text(i), v)

    def do_call(self, n):
        fn, argn = n[1], n[2]; args = [self.ev(a) for a in argn]
        return self.call_with(fn, args)

    def call_with(self, fn, args):
        if fn[0] == "member":
            o = self.ev(fn[1]); name = fn[2]
            if o is self.this and name.lower() == "trigger" and args:
                self.fire_trigger(o, text(args[0]), args[1:]); return None
            if isinstance(o, Obj):
                r = o.call(name.lower(), args)
                return r if r is not None else introspect(o, name.lower(), args)
            if name.lower() in ("add", "addarray") and not isinstance(o, list) and (o is None or o == 0 or o == ""):
                o = []; self.assign_to(fn[1], o)
            return self.method(o, name.lower(), args)
        if fn[0] == "call":
            f = self.ev(fn)
            return f.invoke(args) if isinstance(f, FuncRef) else None
        if fn[0] != "name": return None
        name = fn[1]; low = name.lower()
        for o in reversed(self.active_withs()):
            if isinstance(o, Obj) and low not in self.funcs and low not in BUILTINS:
                r = o.call(low, args)
                if r is not None: return r
        if low == "makevar" and args: return self.makevar(text(args[0]))
        if low in ("loadclass", "joinclass") and args: return self.join(text(args[0]))
        if low in ("printf", "echo") and args: self.host.s.log.append("echo: " + _format(text(args[0]), args[1:])); return None
        if low in ("getcallstack",): return []
        if low in self.funcs:
            val = None
            for f in list(self.funcs[low]): val = self.call_sync(f, args)
            return val
        if low in BUILTINS: return BUILTINS[low](*args) if _arity_ok(BUILTINS[low], len(args)) else None
        if low == "join" and args: return self.join(text(args[0]))
        if low == "trigger" and args: self.fire_trigger(self.this, text(args[0]), args[1:]); return None
        if low == "waitfor": return 0.0
        if low == "sleep": return None
        return self.host.call(low, args, self)

    def makevar(self, path):
        """makevar("a.b"): the variable / function named by the string (functions come back as callable references)."""
        parts = [p for p in re.split(r"\.", path) if p]
        if not parts: return None
        if len(parts) == 1 and parts[0].lower() in self.funcs: return FuncRef(self, parts[0].lower())
        o = self.read_name(parts[0])
        for k, p in enumerate(parts[1:], 1):
            if isinstance(o, ThisObj) and p.lower() in o.interp.funcs and k == len(parts) - 1: return FuncRef(o.interp, p.lower())
            o = self.get_attr(o, p)
        return o

    def method(self, o, name, args):
        if name == "type": return 4.0 if o is None else 1.0 if isinstance(o, str) else 3.0 if isinstance(o, list) else 0.0 if isinstance(o, (int, float)) else 2.0
        if isinstance(o, list):
            if name == "size": return float(len(o))
            if name == "add": o.append(args[0] if args else None); return None
            if name == "clear": o.clear(); return None
            if name == "remove" and args: i = int(num(args[0])); o.pop(i) if 0 <= i < len(o) else None; return None
            if name == "index" and args: return float(next((i for i, x in enumerate(o) if equal(x, args[0])), -1))
            if name == "trim": return [text(x).strip() for x in o]
            if name == "addarray" and args and isinstance(args[0], list): o.extend(args[0]); return None
            if name in ("sortascending", "sortdescending"): o.sort(key=lambda x: (isinstance(x, str), num(x) if not isinstance(x, str) else 0.0, text(x).lower()), reverse=name == "sortdescending"); return None
            if name == "loadlines" and args: return _load_lines(o, args[0])
            if name == "savelines" and args: return _save_lines(o, args[0])
            if name == "loadfolder" and args: return _load_folder(o, args[0])
            if name == "tostring": return ",".join(text(x) for x in o)
            return None
        if o is None: return None
        if isinstance(o, (int, float)) and not isinstance(o, bool): o = text(o)
        if isinstance(o, str):
            if name == "length": return float(len(o))
            if name == "substring" and args:
                a = int(num(args[0])); n = int(num(args[1])) if len(args) > 1 else -1
                return o[a:a + n] if n >= 0 else o[a:]
            if name == "pos" and args: return float(o.lower().find(text(args[0]).lower()))
            if name == "tokenize":
                sep = text(args[0]) if args else None
                return [t for t in (o.split(sep) if sep else o.split())]
            if name == "starts" and args: return 1.0 if o.lower().startswith(text(args[0]).lower()) else 0.0
            if name == "ends" and args: return 1.0 if o.lower().endswith(text(args[0]).lower()) else 0.0
            if name == "contains" and args: return 1.0 if text(args[0]).lower() in o.lower() else 0.0
            if name == "trim": return o.strip()
            if name == "lower": return o.lower()
            if name == "upper": return o.upper()
            if name == "replace" and len(args) >= 2: return o.replace(text(args[0]), text(args[1]))
            if name == "charat" and args: i = int(num(args[0])); return o[i] if 0 <= i < len(o) else ""
            if name == "loadstring" and args: p = sandbox_path(args[0]); return open(p, encoding="latin1").read() if p and os.path.isfile(p) else ""
            if name == "savestring" and args:
                p = sandbox_path(args[0], create=True)
                if p: sandbox_write(p, o)
                return None
        return None

    def join(self, cls):
        """join("class"): add the class's functions (they are chained with ours) and run its top-level statements once."""
        if cls.lower() in self.joined or not self.class_loader: return None
        self.joined.add(cls.lower()); src = self.class_loader(cls)
        if src is None: self.host.unknown(f"join:{cls}"); return None
        self.load(src); return None

def _load_lines(arr, name):
    p = sandbox_path(name); arr.clear()
    if p and os.path.isfile(p): arr.extend(open(p, encoding="latin1").read().split("\n"))
    return None

def _save_lines(arr, name):
    p = sandbox_path(name, create=True)
    if p: sandbox_write(p, "\n".join(text(x) for x in arr))
    return None

def _load_folder(arr, pattern):
    import fnmatch
    pat = text(pattern).replace("\\", "/"); d, _, mask = pat.rpartition("/"); root = sandbox_path(d or ".") if d else SANDBOX
    arr.clear()
    if root and os.path.isdir(root): arr.extend(sorted(f for f in os.listdir(root) if fnmatch.fnmatch(f.lower(), (mask or "*").lower())))
    return None

class FuncRef(Obj):
    """A function value (what makevar("fname") returns): called with `ref(args)` in the script."""
    objtype = "Function"
    def __init__(self, interp, name): self.interp, self.name = interp, name
    def get(self, n): return self.name if n == "name" else None
    def invoke(self, args):
        val = None
        for f in list(self.interp.funcs.get(self.name, [])): val = self.interp.call_sync(f, list(args))
        return val

class ThisObj(DictObj):
    """`this` of a script: variables of the script object plus methods (user functions, join, hasfunction, trigger, ...)."""
    objtype = "Script"
    def funcnames(self): return list(self.interp.funcs)
    def __init__(self, interp, name=""): super().__init__(); self.interp, self.name = interp, name
    def get(self, name):
        if name == "name": return self.name or None
        if name == "id": return self.name or None
        return self.d.get(name)
    def call(self, name, args):
        it = self.interp
        if name in it.funcs: return FuncRef(it, name).invoke(args)
        if name == "join" and args: return it.join(text(args[0]))
        if name == "hasfunction" and args: return 1.0 if text(args[0]).lower() in it.funcs else 0.0
        if name == "trigger" and args:
            it.fire_trigger(self, text(args[0]), args[1:]); return None
        return None

def _arity_ok(f, n):
    try: return f.__code__.co_argcount >= n or f.__code__.co_flags & 4
    except AttributeError: return True

def _format(fmt, args):
    it = iter(args)
    def rep(m):
        try: v = next(it)
        except StopIteration: return ""
        return str(int(num(v))) if m.group(0) in ("%d", "%i") else text(v)
    return re.sub(r"%[sdi]", rep, fmt)

def _rnd(a=0.0, b=1.0): return random.uniform(num(a), num(b)) if REAL_RANDOM[0] else (num(a) + num(b)) / 2
REAL_RANDOM = [False]

BUILTINS = {
    "random": _rnd, "int": lambda v: float(int(num(v))), "abs": lambda v: abs(num(v)), "sin": lambda v: math.sin(num(v)), "cos": lambda v: math.cos(num(v)),
    "tan": lambda v: math.tan(num(v)), "sqrt": lambda v: math.sqrt(max(0.0, num(v))), "min": lambda a, b: min(num(a), num(b)), "max": lambda a, b: max(num(a), num(b)),
    "floor": lambda v: float(math.floor(num(v))), "ceil": lambda v: float(math.ceil(num(v))), "round": lambda v: float(round(num(v))),
    "degtorad": lambda v: math.radians(num(v)), "radtodeg": lambda v: math.degrees(num(v)), "atan2": lambda y, x: math.atan2(num(y), num(x)),
    "getangle": lambda dx, dy: math.atan2(-num(dy), num(dx)) % (2 * math.pi), "vecx": lambda d: float((0, -1, 0, 1)[int(num(d)) & 3]),
    "vecy": lambda d: float((-1, 0, 1, 0)[int(num(d)) & 3]), "strlen": lambda s: float(len(text(s))), "strequals": lambda a, b: 1.0 if equal(a, b) else 0.0,
    "strtofloat": num, "strtoint": lambda v: float(int(num(v))), "tostring": text, "format": lambda f, *a: _format(text(f), a), "_": lambda s: text(s), "sqr": lambda v: num(v) ** 2,
    "lower": lambda s: text(s).lower(), "upper": lambda s: text(s).upper(), "startswith": lambda a, b: 1.0 if text(b).lower().startswith(text(a).lower()) else 0.0,
    "endswith": lambda a, b: 1.0 if text(b).lower().endswith(text(a).lower()) else 0.0, "timevar": lambda: time.time(), "timevar2": lambda: time.time(),
    "distance": lambda x1, y1, x2, y2: math.hypot(num(x2) - num(x1), num(y2) - num(y1)), "sign": lambda v: float((num(v) > 0) - (num(v) < 0)),
    "arraylen": lambda a: float(len(a)) if isinstance(a, list) else 0.0, "strreplace": lambda s, a, b: text(s).replace(text(a), text(b)),
    "substring": lambda s, a, n=None: text(s)[int(num(a)):] if n is None else text(s)[int(num(a)):int(num(a)) + int(num(n))], "makevar": lambda s: text(s),
    "makevar2": lambda s: text(s), "isobject": lambda o: 1.0 if isinstance(o, Obj) else 0.0, "setarray": lambda n, size=0: [0.0] * int(num(size)),
}
