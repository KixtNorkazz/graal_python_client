"""Client-side weapon scripts (GS1 subset) for 'gani weapons': setani / replaceani / freezeplayer / setplayerprop / setstring,
events weaponfired, timeout, playershootssword, playerchats, with `sleep` as a coroutine pause. The weapon script runs from the part
after `//#CLIENTSIDE` (the first part is server-side)."""
import safeexpr
import math, re, time, warnings
warnings.filterwarnings("ignore", category=SyntaxWarning)

EVENTS = ("playerdies", "weaponfired", "timeout", "playerenters", "playerchats", "playershootssword", "washit", "wasshot", "wasexploded", "wasthrown", "created", "playertouchsme", "playerleaves", "movementfinished", "mousedown", "mouseup", "mousemove", "keypressed")

def client_part(script: str) -> str:
    m = re.search(r"//#?CLIENTSIDE", script)
    return script[m.end():] if m else script

def server_part(script: str) -> str:
    """The text before `//#CLIENTSIDE` (what the server runs); '' when the script has no marker."""
    m = re.search(r"//#?CLIENTSIDE", script)
    return script[:m.start()] if m else ""

def strip_comments(s):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", s, flags=re.S))

def _balanced(s, i, open_, close):
    depth = 0
    for j in range(i, len(s)):
        if s[j] == open_: depth += 1
        elif s[j] == close:
            depth -= 1
            if depth == 0: return j
    return len(s) - 1

def _split_semis(h):
    out, depth, cur = [], 0, ""
    for ch in h:
        if ch in "({": depth += 1
        elif ch in ")}": depth -= 1
        if ch == ";" and depth == 0: out.append(cur.strip()); cur = ""
        else: cur += ch
    out.append(cur.strip())
    return out

def collect_funcs(nodes, out=None):
    """User functions (`function name(a,b) {...}`) defined anywhere in a parsed script: lowercase name -> (params, body)."""
    out = {} if out is None else out
    for n in nodes:
        if n[0] == "func": out[n[1]] = (n[2], n[3])
        elif n[0] == "block": collect_funcs(n[1], out)
    return out

def parse(text):
    """-> list of nodes: ('if', cond, then, else_or_None) | ('block', [nodes]) | ('cmd', text)"""
    text = strip_comments(text); pos = [0]; n = len(text)
    def ws():
        while pos[0] < n and text[pos[0]] in " \t\r\n": pos[0] += 1
    def stmt():
        ws()
        if pos[0] >= n: return None
        c = text[pos[0]]
        if c == "{":
            end = _balanced(text, pos[0], "{", "}"); inner = text[pos[0] + 1:end]; pos[0] = end + 1
            return ("block", parse(inner))
        if c == "}" or c == ";": pos[0] += 1; return stmt()
        m = re.match(r"function\s+(\w+)\s*\(([^)]*)\)\s*\{", text[pos[0]:])
        if m:
            p0 = pos[0] + m.end() - 1; end = _balanced(text, p0, "{", "}"); body = parse(text[p0 + 1:end]); pos[0] = end + 1
            return ("func", m.group(1).lower(), [p.strip() for p in m.group(2).split(",") if p.strip()], body)
        m = re.match(r"if\s*\(", text[pos[0]:])
        if m:
            p0 = pos[0] + m.end() - 1; end = _balanced(text, p0, "(", ")"); cond = text[p0 + 1:end]; pos[0] = end + 1
            then = stmt(); ws(); els = None
            if re.match(r"else\b", text[pos[0]:]): pos[0] += 4; els = stmt()
            elif re.match(r"elseif\s*\(", text[pos[0]:]): pos[0] += 4; els = stmt()
            return ("if", cond, then, els)
        m = re.match(r"(for|while)\s*\(", text[pos[0]:])
        if m:
            p0 = pos[0] + m.end() - 1; end = _balanced(text, p0, "(", ")"); head = text[p0 + 1:end]; pos[0] = end + 1
            body = stmt()
            if m.group(1) == "while": return ("while", head, body)
            parts = _split_semis(head)
            if len(parts) == 3: return ("for", parts[0], parts[1], parts[2], body)
            return ("block", [])
        depth = 0; j = pos[0]
        arr = False
        while j < n and not (text[j] == ";" and depth == 0):
            if text[j] in "({": depth += 1
            elif text[j] in ")}":
                depth -= 1
                if text[j] == "}" and depth == 0 and re.match(r"\w+[ (].*,\s*\{", text[pos[0]:j + 1], re.S): arr = True; j += 1; break
            j += 1
        cmd = text[pos[0]:j].strip(); pos[0] = j + (0 if arr else 1)
        return ("cmd", cmd) if cmd else stmt()
    out = []
    while True:
        s = stmt()
        if s is None: break
        out.append(s)
    return out

class Ctx:
    """Execution context for one weapon event."""
    def __init__(self, weapon, session, event, chat="", params=()):
        self.w, self.s, self.event, self.chat, self.params = weapon, session, event, chat, list(params)
        self.ret = False; self.depth = 0

def subst(text, ctx):
    """GS1 message codes inside argument text: #s(var) #v(expr) #c (chat) #a (account) #n (nickname) #L (level) #p(n) (event parameter)."""
    t = re.sub(r"#s\(\s*([\w.]+)\s*\)", lambda m: str(ctx.s.vars.get(m.group(1), "")), text)
    t = re.sub(r"#v\((.*?)\)", lambda m: fmt_num(evaluate(m.group(1), ctx)), t)
    t = re.sub(r"#p\((\d+)\)", lambda m: ctx.params[int(m.group(1))] if int(m.group(1)) < len(ctx.params) else "", t)
    t = re.sub(r"#t\((\d+)\)", lambda m: ctx.s.tokens[int(m.group(1))] if int(m.group(1)) < len(ctx.s.tokens) else "", t)
    t = t.replace("#c", ctx.chat)
    t = t.replace("#a", getattr(ctx.s, "account_name", "")).replace("#n", str(ctx.s.me.get("NICKNAME", ""))).replace("#g", str(getattr(ctx.s, "guild", "")))
    return t.replace("#L", str(getattr(ctx.s, "level_name", "") or ""))

def fmt_num(v):
    try:
        f = float(v); return str(int(f)) if f == int(f) else repr(f)
    except (TypeError, ValueError): return str(v)

def _split_args(s):
    out, depth, cur, q = [], 0, "", False
    for ch in s:
        if ch == '"': q = not q
        elif not q and ch in "({": depth += 1
        elif not q and ch in ")}": depth -= 1
        if ch == "," and depth == 0 and not q: out.append(cur); cur = ""
        else: cur += ch
    out.append(cur)
    return [a.strip() for a in out]

def unquote(a):
    return a[1:-1].replace('""', '"') if len(a) >= 2 and a[0] == a[-1] == '"' else a

def to_float(v):
    try: return float(v)
    except (TypeError, ValueError): return 0.0

import random as _random
_RNG = _random.Random(); REAL_RANDOM = False

_FUNCS = {"strtofloat", "strequals", "startswith", "int", "abs", "random", "and", "or", "not", "T", "S", "True", "False", "sin", "cos", "getangle", "vecx", "vecy", "onwall", "keydown", "hasweapon", "imgwidth", "imgheight", "arraylen", "tiles_", "keydown2", "keycode", "onwater", "strcontains", "strreplace"}

_STATS = {"playerrupees", "playergralats", "playerbombs", "playerdarts", "playerarrows", "playerhearts", "playerfullhearts", "playerswordpower", "playershieldpower", "playerglovepower"}

def _stat(s, name):
    """GS1 player statistics from the player's props (set by the server; the walking / door planner may override them on a shadow session)."""
    me = s.me
    if name in ("playerrupees", "playergralats"): return float(me.get("GRALATS", 0) or 0)
    if name == "playerbombs": return float(me.get("BOMBS", 0) or 0)
    if name in ("playerdarts", "playerarrows"): return float(me.get("ARROWS", 0) or 0)
    if name == "playerhearts": return float(me.get("HALFHEARTS", 0) or 0) / 2
    if name == "playerfullhearts": return float(me.get("FULLHEARTS", 0) or 0)
    if name == "playerswordpower": return float((me.get("SWORDIMAGE") or {}).get("power", 1))
    if name == "playershieldpower": return float((me.get("SHIELDIMAGE") or {}).get("power", 0))
    return float(me.get("GLOVEPOWER", 0) or 0)

_STAT_LIMITS = {"GRALATS": 9999999, "BOMBS": 99, "ARROWS": 99}

def set_stat(s, name, v):
    """Assign a GS1 player statistic (`playerrupees -= 10`): the player's props, clamped like the server does."""
    if name in ("playerrupees", "playergralats"): prop = "GRALATS"
    elif name == "playerbombs": prop = "BOMBS"
    elif name in ("playerdarts", "playerarrows"): prop = "ARROWS"
    elif name == "playerhearts": s.me["HALFHEARTS"] = max(0, int(round(v * 2))); s.send_hearts(); return
    else: return
    s.me[prop] = max(0, min(_STAT_LIMITS[prop], int(v)))

def _img_size(name):
    """(width, height) in px of an image file (0, 0 when it cannot be loaded)."""
    try:
        import render
        im = render.load_image(str(name))
        return (float(im.width), float(im.height)) if im is not None else (0.0, 0.0)
    except Exception: return (0.0, 0.0)

def _keycode(c):
    """GS1 keycode(c): the Windows virtual-key code of a character (letters upper case, digits as themselves, a number is the digit's key)."""
    import inputs
    if isinstance(c, (int, float)) and not isinstance(c, bool): c = str(int(c))
    c = str(c)[:1]
    return float(inputs.sdl_to_vk(ord(c.lower()))) if c else 0.0

def _water(ctx, x, y):
    """GS1 onwater(x,y): is the tile at level-local tile (x,y) water (tile types 11 / 12)?"""
    from tiletypes import TYPE0
    return 1.0 if TYPE0[_tile_at(ctx, x, y)] in (11, 12) else 0.0

def _tile_at(ctx, x, y):
    lv = ctx.s.levels.get(getattr(ctx.w, "level", None) or ctx.s.level_name); tx, ty = int(to_float(x)), int(to_float(y))
    return lv.tile(tx, ty) & 0xFFF if lv and lv.board and 0 <= tx < 64 and 0 <= ty < 64 else 0

class _Zero(float):
    """An unset variable: 0, and an array whose elements read as 0 (GS1 creates arrays on first use)."""
    def __getitem__(self, i): return 0.0

class _Arr(list):
    """A GS1 array in an expression: float indexes, out of range reads as 0."""
    def __getitem__(self, i):
        try: i = int(i)
        except (TypeError, ValueError): return 0.0
        return list.__getitem__(self, i) if 0 <= i < len(self) else 0.0

_CODE = {}

def evaluate(expr, ctx):
    """Evaluate a GS1 expression to a Python value (numbers, strings, bools). Unknown things become 0 / ''."""
    e = expr.strip()
    if not e: return 0.0
    if "\n" in e: e = " ".join(e.split())
    if ";" in e: e = re.sub(r";\s*(?=(?:or|and)\b|\|\||&&)", " ", e)
    if "0x" in e or "0X" in e: e = re.sub(r"\b0[xX]([0-9A-Fa-f]+)\b", lambda m: str(int(m.group(1), 16)), e)
    S = lambda name: ctx.s.vars.get(name, "")
    def one(a):
        a = a.strip()
        return a if re.fullmatch(r"#[acgnL]|#s\([^)]*\)|#v\(.*\)|#[pt]\(\d+\)|\"[^\"]*\"|-?\d+\.?\d*|this\.\w+", a) else "\"" + a.replace("\"", "") + "\""
    def lit(m): return f"{m.group(1)}({one(m.group(2))},{one(m.group(3))})"
    if "keycode(" in e: e = re.sub(r"\bkeycode\(([^()]*)\)", lambda m: f"keycode({one(m.group(1))})", e)
    if "hasweapon(" in e: e = re.sub(r"\bhasweapon\(([^,()]*(?:\([^()]*\))?[^,()]*)\)", lambda m: f"hasweapon({one(m.group(1))})", e)
    if "strreplace(" in e: e = re.sub(r"\bstrreplace\(([^,()]*),([^,()]*),([^,()]*)\)", lambda m: f"strreplace({one(m.group(1))},{one(m.group(2))},{one(m.group(3))})", e)
    if "strcontains(" in e: e = re.sub(r"\bstrcontains\(([^,()]*(?:\([^()]*\))?[^,()]*),([^()]*(?:\([^()]*\))?[^()]*)\)", lambda m: f"strcontains({one(m.group(1))},{one(m.group(2))})", e)
    if "strequals(" in e or "startswith(" in e: e = re.sub(r"\b(strequals|startswith)\(([^,()]*(?:\([^()]*\))?[^,()]*),([^()]*(?:\([^()]*\))?[^()]*)\)", lit, e)
    if "#s(" in e: e = re.sub(r"#s\(\s*([\w.]+)\s*\)", lambda m: repr(S(m.group(1))), e)
    if "#t(" in e: e = re.sub(r"#t\((\d+)\)", lambda m: repr(ctx.s.tokens[int(m.group(1))] if int(m.group(1)) < len(ctx.s.tokens) else ""), e)
    if "#c" in e: e = re.sub(r"#c\b", lambda m: repr(ctx.chat), e)
    if "#f" in e: e = re.sub(r"#f\b", lambda m: repr(str(getattr(getattr(ctx.w, "fx", None), "image", "") or getattr(ctx.w, "image", ""))), e)
    if "#g" in e: e = re.sub(r"#g\b", lambda m: repr(str(getattr(ctx.s, "guild", ""))), e)
    if "#a" in e: e = re.sub(r"#a\b", lambda m: repr(str(getattr(ctx.s, "account_name", ""))), e)
    if "#p(" in e: e = re.sub(r"#p\((\d+)\)", lambda m: repr(ctx.params[int(m.group(1))] if int(m.group(1)) < len(ctx.params) else ""), e)
    if "#v(" in e: e = re.sub(r"#v\((.*?)\)", lambda m: repr(str(evaluate(m.group(1), ctx))), e)
    flags = {f: (f == ctx.event) for f in EVENTS}
    def ident(m):
        w = m.group(0)
        if w in flags: return str(flags[w])
        npc = getattr(ctx.w, "is_npc", False)
        if npc and w in ("x", "y"): return repr(getattr(ctx.w.fx, w))
        if w.lower().startswith("action") and len(w) > 6: return str(ctx.event.lower() == w.lower())
        if w == "tokenscount": return str(float(len(ctx.s.tokens)))
        if w in ("leftmousebutton", "rightmousebutton", "middlemousebutton"): return "1.0" if ctx.s.input.button(w[:-11]) else "0.0"
        if w in ("mousex", "mousey"): return repr(ctx.s.input.world()[0 if w == "mousex" else 1])
        if w in ("mousescreenx", "mousescreeny"): return repr(ctx.s.input.sx if w == "mousescreenx" else ctx.s.input.sy)
        if w == "pi": return repr(math.pi)
        if w == "timevar": return repr(float(ctx.s.vars.get("timevar") or int(ctx.s.clock())))
        if w == "playerz": return "0.0"
        if w in _STATS: return repr(_stat(ctx.s, w))
        if w == "playerdir": return repr(float(ctx.s.me.get("SPRITE", 2) & 3))
        if w == "playerattached": return str(getattr(ctx.s, "attached", None) is not None and getattr(ctx.s, "attached", None) == getattr(ctx.w, "nid", object()))
        if w == "playerx": return repr(ctx.s.pos[0] / 16)
        if w == "playery": return repr(ctx.s.pos[1] / 16)
        if w.startswith("this."): return f"T[{w[5:]!r}]"
        if w in ("true", "false"): return w.capitalize()
        if w == "in_": return " in "
        if w in _FUNCS: return w
        if w == "timeout": return str(ctx.event == "timeout")
        if w in ctx.s.flags: return "True"
        if npc and re.fullmatch(r"[A-Za-z_]\w*", w) and w not in _FUNCS: return f"T[{w!r}]"
        if re.fullmatch(r"(\d+\.?\d*|\.\d+)", w): return w
        if re.search(r"\.(png|gif|mng|gani|wav|txt|nw)$", w, re.I): return repr(w)
        if "." in w: return "0.0"
        return repr(w) if re.search(r"[A-Za-z]", w) else w
    class _M:
        def __init__(self, w): self.w = w
        def group(self, k=0): return self.w
    def word(m):
        w = m.group(0)
        if "-" in w and not re.search(r"\.(png|gif|mng|gani|wav|txt|nw)$", w, re.I):
            parts = w.split("-"); first = ident(_M(parts[0]))
            if first != repr(parts[0]) and re.fullmatch(r"[A-Za-z_][\w.]*", parts[0]): return "-".join(ident(_M(p)) if p else "" for p in parts)
        return ident(m)
    if "in" in e and "|" in e: e = re.sub(r"([\w.]+(?:\([^()]*\))?)\s+in\s*\|\s*([^,|]+),([^|]+)\|", r"(\2 <= \1 <= \3)", e)
    if "=" in e and ("<" in e or ">" in e): e = re.sub(r"=\s*<(?!=)", "<=", re.sub(r"=\s*>(?!=)", ">=", e))
    if "tiles[" in e: e = re.sub(r"\btiles\[([^\[\],]+),([^\[\],]+)\]", r"tiles_(\1,\2)", e)
    if " in" in e: e = re.sub(r"\bin\s+(?!\|)([A-Za-z_][\w.]*)", r" in_ \1", e)
    e = e.replace("&&", " and ").replace("||", " or ").replace("^", "**")
    e = re.sub(r"(?<![=!<>])!(?!=)", " not ", e)
    e = re.sub(r"(?<![=!<>])=(?!=)", "==", e)
    e = re.sub(r"'(?:[^'\\]|\\.)*'|\"[^\"]*\"|\.?\d+\.?\d*|[A-Za-z_][\w.\-]*", lambda m: m.group(0) if m.group(0)[0] in "'\"" else word(m), e)
    env = {"__builtins__": {}, "T": ctx.w.this, "strtofloat": to_float, "int": lambda v: int(to_float(v)), "abs": abs, "sin": math.sin, "cos": math.cos,
           "vecx": lambda d: (0, -1, 0, 1)[int(to_float(d)) & 3], "vecy": lambda d: (-1, 0, 1, 0)[int(to_float(d)) & 3],
           "keydown": lambda k: 1.0 if ctx.s.input.is_down(to_float(k)) else 0.0,
           "imgwidth": lambda n: _img_size(n)[0], "imgheight": lambda n: _img_size(n)[1],
           "hasweapon": lambda n: 1.0 if ctx.s.has_weapon(str(n)) else 0.0,
           "onwall": lambda x, y: ctx.s.onwall(to_float(x), to_float(y), getattr(ctx.w, "level", None)),
           "getangle": lambda vx, vy: math.atan2(-to_float(vy), to_float(vx)) % (2 * math.pi),
           "strequals": lambda a, b: str(a).lower() == str(b).lower(), "startswith": lambda a, b: str(b).lower().startswith(str(a).lower()),
           "random": lambda a=0, b=1: (_RNG.uniform(to_float(a), to_float(b)) if REAL_RANDOM else (to_float(a) + to_float(b)) / 2)}
    class _T(dict):
        def __missing__(self, k): return _Zero(0.0)
        def __getitem__(self, k):
            v = dict.__getitem__(self, k) if k in self else _Zero(0.0)
            return _Arr(v) if isinstance(v, list) else v
    env["T"] = _T(ctx.w.this); env["keycode"] = _keycode; env["strreplace"] = lambda a, b, c: str(a).strip("'\"").replace(str(b).strip("'\""), str(c).strip("'\"")); env["strcontains"] = lambda a, b: str(b).lower() in str(a).lower(); env["onwater"] = lambda x, y: _water(ctx, x, y); env["keydown2"] = lambda k, f=1: 1.0 if ctx.s.input.vk_is_down(to_float(k)) else 0.0; env["tiles_"] = lambda x, y: float(_tile_at(ctx, x, y)); env["arraylen"] = lambda a: float(len(a)) if isinstance(a, list) else 0.0
    env["_pow_"] = lambda a, b: safeexpr.safe_pow(to_float(a), to_float(b)); env["_mul_"] = lambda a, b: safeexpr.safe_mul(to_float(a), to_float(b))
    code = _CODE.get(e, 0)
    if code == 0:
        code = safeexpr.compile_expr(e)   # no attribute access (sandbox escape), no shifts, float ** and * (no huge ints)
        if len(_CODE) > 20000: _CODE.clear()
        _CODE[e] = code
    if code is None: return 0.0
    try: return eval(code, env)
    except Exception: return 0.0

def run_nodes(nodes, ctx):
    """Generator; yields a delay (seconds) at every `sleep`."""
    for node in nodes:
        if ctx.ret: return
        kind = node[0]
        if kind == "func": continue
        if kind == "block": yield from run_nodes(node[1], ctx)
        elif kind == "if":
            if evaluate(node[1], ctx): yield from run_nodes([node[2]] if node[2] else [], ctx)
            elif node[3]: yield from run_nodes([node[3]], ctx)
        elif kind in ("for", "while"):
            if kind == "for" and node[1]: yield_command(node[1], ctx)
            cond, step, body = (node[2], node[3], node[4]) if kind == "for" else (node[1], "", node[2])
            for _ in range(2000):
                if not (evaluate(cond, ctx) if cond.strip() else True): break
                if body: yield from run_nodes([body], ctx)
                if step: yield_command(step, ctx)
        else:
            call = re.fullmatch(r"(\w+)\s*\((.*)\)", node[1], re.S)
            fn = getattr(ctx.w, "funcs", {}).get(call.group(1).lower()) if call else None
            if fn is not None:
                if ctx.depth < 40:
                    for pn, a in zip(fn[0], _split_args(call.group(2))): ctx.w.this[pn] = evaluate(a, ctx)
                    ctx.depth += 1; yield from run_nodes(fn[1], ctx); ctx.depth -= 1
                ctx.ret = False
                continue
            d = yield_command(node[1], ctx)
            if d:
                yield d
                ctx.event = ""

def yield_command(cmd, ctx):
    """Run one command; return a sleep duration (seconds) or 0."""
    s = ctx.s; w = ctx.w; cmd = cmd.strip()
    b = getattr(s, "sim_budget", None)
    if b is not None:
        b[0] -= 1
        if b[0] < 0: raise RuntimeError("simulation budget exhausted")
    m = re.match(r"([\w.]+)\[(.+?)\]\s*(?:([+\-*/])?=(?!=)\s*(.*)|(\+\+|--)())$", cmd, re.S)
    if m and (name_ := m.group(1)) and (name_.startswith("this.") or getattr(w, "is_npc", False)):
        key = name_[5:] if name_.startswith("this.") else name_; lst = w.this.get(key)
        if not isinstance(lst, list): lst = w.this[key] = []
        i_ = int(to_float(evaluate(m.group(2), ctx)))
        if i_ < 0 or i_ > 100000: return 0
        if i_ >= len(lst): lst.extend([0.0] * (i_ + 1 - len(lst)))
        op = m.group(3) or (m.group(5) or "")[:1] or None; v = 1.0 if m.group(5) else evaluate(m.group(4), ctx)
        if op:
            a_, b_ = to_float(lst[i_]), to_float(v); v = {"+": a_ + b_, "-": a_ - b_, "*": a_ * b_, "/": a_ / b_ if b_ else a_}[op]
        lst[i_] = v
        if getattr(w, "is_npc", False): w.rt.version += 1
        return 0
    m = re.match(r"([\w.]+)\s*([+\-*/])?=(?!=)\s*(.*)$", cmd, re.S) or re.match(r"([\w.]+)\s*(\+\+|--)()$", cmd)
    if m:
        name, op, rhs = m.group(1), m.group(2), m.group(3)
        npc = getattr(w, "is_npc", False)
        if op in ("++", "--"): v, op = 1.0, op[0]
        elif not op and rhs.strip().startswith("{") and rhs.strip().endswith("}") and (name.startswith("this.") or npc):
            w.this[name[5:] if name.startswith("this.") else name] = [to_float(evaluate(p, ctx)) for p in _split_args(rhs.strip()[1:-1]) if p.strip()]; return 0
        else: v = evaluate(rhs, ctx)
        if name in ("playerx", "playery", "playerdir"):
            a_ = {"playerx": ctx.s.pos[0] / 16, "playery": ctx.s.pos[1] / 16, "playerdir": float(ctx.s.me.get("SPRITE", 2) & 3)}[name]; b_ = to_float(v)
            nv = {None: b_, "+": a_ + b_, "-": a_ - b_, "*": a_ * b_, "/": a_ / b_ if b_ else a_}[op]
            if name == "playerdir": ctx.s.me["SPRITE"] = (ctx.s.me.get("SPRITE", 2) & ~3) | (int(nv) & 3)
            else:
                ctx.s.pos = (int(nv * 16), ctx.s.pos[1]) if name == "playerx" else (ctx.s.pos[0], int(nv * 16))
                if hasattr(ctx.s, "moved_by_script"): ctx.s.moved_by_script()
            return 0
        if name in _STATS:
            a_, b_ = _stat(s, name), to_float(v)
            set_stat(s, name, {None: b_, "+": a_ + b_, "-": a_ - b_, "*": a_ * b_, "/": a_ / b_ if b_ else a_}[op]); return 0
        key = name[5:] if name.startswith("this.") else name
        if npc and name in ("x", "y"): cur = getattr(w.fx, name)
        elif name == "timeout": cur = 0.0
        else: cur = w.this.get(key, 0.0) if (name.startswith("this.") or npc) else 0.0
        if op:
            a_, b_ = to_float(cur), to_float(v)
            v = {"+": a_ + b_, "-": a_ - b_, "*": a_ * b_, "/": a_ / b_ if b_ else a_}[op]
        if name == "timeout": w.timeout_at = (s.clock() if getattr(w, "is_npc", False) else time.time()) + to_float(v) if to_float(v) > 0 else None
        elif npc and name in ("x", "y"): setattr(w.fx, name, to_float(v)); w.rt.version += 1
        elif name.startswith("this.") or npc: w.this[key] = v
        return 0
    m = re.match(r"(\w+)\s*(?:\((.*)\)|\s+(.*))?$", cmd, re.S)
    if not m: return 0
    name = m.group(1).lower(); arg = (m.group(2) if m.group(2) is not None else m.group(3)) or ""
    args = _split_args(arg)
    val = lambda k, d="": (evaluate(args[k], ctx) if k < len(args) and args[k] != "" else d)
    txt = lambda k: unquote(subst(args[k], ctx).strip()) if k < len(args) else ""
    if name == "sleep": return to_float(val(0))
    if name == "return": ctx.ret = True; return 0
    if name == "putbomb" and len(args) >= 3: s.bombs.put(to_float(val(1)), to_float(val(2)), int(to_float(val(0))), getattr(w, "cell", None) if s.gmap else None, send=not getattr(w, "is_npc", False)); return 0
    if getattr(w, "is_npc", False) and w.handle(name, args, val, txt, ctx): return 0
    if name == "addweapon" and arg.strip(): s.add_weapon(txt(0))
    elif name == "removeweapon" and arg.strip(): s.remove_weapon(txt(0))
    elif name == "setani": s.play_gani(txt(0), [a for a in (txt(i) for i in range(1, len(args))) if a])
    elif name == "replaceani":
        a, b = txt(0), txt(1)
        if a == b: s.ani_replace.pop(a, None)
        else: s.ani_replace[a] = b
    elif name == "freezeplayer": s.freeze(to_float(val(0)))
    elif name == "triggeraction" and len(args) >= 3:
        s.send_triggeraction(getattr(w, "npc_id", 0), to_float(val(0)), to_float(val(1)), [unquote(subst(a, ctx).strip()) for a in args[2:]])
    elif name == "setstring" and len(args) >= 2: s.vars[subst(args[0], ctx).strip() if "#" in args[0] else args[0].strip()] = txt(1)
    elif name == "setplayerprop" and len(args) >= 2: s.set_player_prop(args[0].strip(), txt(1))
    elif name in ("set", "unset") and arg.strip().lower().startswith("this.") and hasattr(w, "this"):
        key = subst(arg, ctx).strip()[5:]
        if name == "set": w.this[key] = 1.0
        else: w.this.pop(key, None)
    elif name == "set" and arg.strip(): s.set_flag(subst(arg, ctx) if "#" in arg else arg)
    elif name == "unset" and arg.strip(): s.set_flag(subst(arg, ctx) if "#" in arg else arg, False)
    elif name == "tokenize": s.tokens = [t for t in re.split(r"[,\s]+", subst(arg, ctx).strip()) if t != ""]
    elif name == "addstring" and len(args) >= 2: s.arrays.setdefault(args[0].strip(), []).append(txt(1))
    elif name == "deletestring" and len(args) >= 2:
        a = s.arrays.get(args[0].strip(), [])
        if 0 <= int(to_float(val(1))) < len(a): del a[int(to_float(val(1)))]
    elif name == "setarray" and len(args) >= 2:
        n_ = max(0, int(to_float(val(1)))); nm = args[0].strip()
        if nm.startswith("this.") or getattr(w, "is_npc", False):
            key = nm[5:] if nm.startswith("this.") else nm; old_ = w.this.get(key); old_ = old_ if isinstance(old_, list) else []
            w.this[key] = (old_ + [0.0] * n_)[:n_]
        else: s.arrays[nm] = [""] * n_
    elif name == "say2": s.say2(subst(arg, ctx))
    elif name == "showtext" and len(args) >= 6: s.show_text(int(to_float(val(0))), to_float(val(1)), to_float(val(2)), ",".join(txt(i) for i in range(5, len(args))))
    elif name in ("hidetext", "hidetexts") and args: s.hide_text(int(to_float(val(0))))
    elif name == "showimg" and len(args) >= 4: s.show_img(int(to_float(val(0))), txt(1), to_float(val(2)), to_float(val(3)))
    elif name == "changeimgvis" and len(args) >= 2: s.img_prop(int(to_float(val(0))), vis=int(to_float(val(1))))
    elif name == "changeimgcolors" and len(args) >= 5: s.img_prop(int(to_float(val(0))), color=tuple(to_float(val(i)) for i in range(1, 5)))
    elif name == "changeimgzoom" and len(args) >= 2: s.img_prop(int(to_float(val(0))), zoom=to_float(val(1)) or 1.0)
    elif name == "changeimgpart" and len(args) >= 5: s.img_prop(int(to_float(val(0))), part=tuple(int(to_float(val(i))) for i in range(1, 5)))
    elif name == "hideimg" and args: s.hide_imgs(int(to_float(val(0))))
    elif name == "hideimgs" and len(args) >= 2: s.hide_imgs(int(to_float(val(0))), int(to_float(val(1))))
    elif name == "destroy": s.runner.weapons.pop(w.name, None)
    elif name == "seteffect" and len(args) >= 4: s.effect = tuple(to_float(val(i)) for i in range(4))
    elif name in ("setskincolor", "setcoatcolor", "setsleevecolor", "setshoecolor", "setbeltcolor") and args:
        s.set_color(("setskincolor", "setcoatcolor", "setsleevecolor", "setshoecolor", "setbeltcolor").index(name), txt(0))
    elif name == "hurt" and args:
        n_ = to_float(val(0)); s.me["HALFHEARTS"] = max(0, int(s.me.get("HALFHEARTS", 6) - round(n_ * 2))); s.send_hearts()
        if "hurt" not in (s.me.get("GANI") or ""): s.play_gani("hurt", [])
    elif name == "setplayerdir" and args: s.me["SPRITE"] = (s.me.get("SPRITE", 2) & ~3) | (int(to_float(val(0))) & 3)
    elif name == "showstats": s.show_stats = int(to_float(val(0))) if args else 1; s.hud_hidden = False
    elif name == "hidestats": s.show_stats = 0; s.hud_hidden = True
    elif name == "showlocal": s.show_local = True
    elif name == "noplayerkilling": s.no_pk = True
    elif name == "puthorse" and len(args) >= 3:
        h_ = (txt(0), to_float(val(1)), to_float(val(2)), s.cell if s.gmap else (0, 0))
        if h_ not in s.horses and not any(o[:3] == h_[:3] for o in s.horses): s.horses.append(h_)
    elif name == "enableweapons": s.weapons_enabled = True
    elif name == "disableweapons": s.weapons_enabled = False
    elif name == "enabledefmovement": s.defmovement = True
    elif name == "disabledefmovement": s.defmovement = False
    elif name in ("play", "playlooped") and args: s.play_sound(txt(0), loop=(name == "playlooped"), from_weapon=isinstance(ctx.w, Weapon))
    elif name == "shoot" and len(args) >= 7:
        s.proj.shoot(*(to_float(val(k)) for k in range(6)), txt(6), [txt(k) for k in range(7, len(args)) if txt(k) != ""])
    elif name == "setshootparams": s.proj.shootparams = [txt(k) for k in range(len(args)) if txt(k) != ""]
    elif name == "loadmap" and args: s.load_map(txt(0))
    elif name in ("removetiledefs", "addtiledef", "addtiledef2"): pass
    elif name == "stopmidi": s.stop_sound()
    elif name == "stopsound": s.stop_sound(txt(0) if args else None)
    elif name == "setfocus" and len(args) >= 2: s.set_focus(to_float(val(0)), to_float(val(1)), getattr(w, "cell", None) if s.gmap else None)
    elif name == "resetfocus": s.focus = None
    elif name == "showpoly" and len(args) >= 2: s.show_poly(txt(0), [to_float(evaluate(p, ctx)) for p in _split_args(",".join(args[1:]).strip().strip("{}").rstrip(";").strip()) if p != ""])
    elif name in ("hidepoly", "hidepolys") and args: s.hide_poly(txt(0))
    elif name == "wraptext2" and len(args) >= 4: s.wrap_text(to_float(val(0)), subst(",".join(args[3:]), ctx))
    elif name == "timereverywhere": pass
    elif name in ("setlevel2", "shoot", "setshootparams", "move", "message", "sendrpgmessage", "putnpc2", "showpoly", "echo", "toweapons", "refresh"): s.unsupported[name] = s.unsupported.get(name, 0) + 1
    elif name in ("toweapons", "say2", "tokenize", "setcharani", "set", "unset", "setlevel2", "hideimg", "showimg", "dontblock"): pass
    else: s.unsupported[name] = s.unsupported.get(name, 0) + 1
    return 0

def _server_joins(script):
    """Classes joined in the server part (before //#CLIENTSIDE): the server sends their client parts along, so the client script has them too."""
    m = re.search(r"//#?CLIENTSIDE", script or "")
    return re.findall(r"\bjoin\s*\(\s*\"([\w\-.]+)\"\s*\)", script[:m.start()]) if m else []

class Weapon:
    def __init__(self, name, image, script, session=None):
        self.name, self.image, self.script = name, image, script
        self.nodes = parse(client_part(script)); self.funcs = collect_funcs(self.nodes); self.this = {}; self.timeout_at = None; self.tasks = []
        self.has = lambda ev: ev in script; self.gs2 = None; self.host = None
        import gs2npc
        if gs2npc.is_gs2(script) and session is not None:
            import gs2src
            self.host = gs2npc.WeaponHost(self, session)
            try:
                self.gs2 = gs2src.Interp(self.host, client_part(script), gs2npc.class_source); self.gs2.this.name = name
                for cls in _server_joins(script): self.gs2.join(cls)
            except gs2src.Gs2Error as e: session.log.append(f"gs2 parse weapon {name}: {e}")

class WeaponRunner:
    def __init__(self, session): self.s, self.weapons, self.selected = session, {}, None   # selected: name of the weapon chosen in the inventory

    def add(self, name, image, script):
        self.weapons[name] = Weapon(name, image, script, self.s)
        wp = self.weapons[name]
        self.s.npcserver.attach(wp, self.s)
        if wp.gs2 and wp.gs2.has_function("oncreated"): self.run_event(wp, "created")

    def script_object(self, low):
        """A GS2 weapon as a global object (`Console.msg(...)` from another script): matched by its name without the leading -+#* marks."""
        for w in self.weapons.values():
            if w.gs2 and re.sub(r"^[^A-Za-z0-9]+", "", w.name).lower() == low: return w.gs2.this
        return None

    def firable(self):
        return [w for w in self.weapons.values() if not w.name.startswith("-") and "weaponfired" in client_part(w.script).lower()]

    def run_event(self, weapon, event, chat="", params=()):
        if weapon.gs2:
            import gs2sched
            weapon.host.chat = chat; gen = gs2sched.GenRunner(weapon.gs2.call_function("on" + event, params), weapon, self.s)
        else: ctx = Ctx(weapon, self.s, event, chat, params); gen = run_nodes(weapon.nodes, ctx)
        self._advance(weapon, gen)

    def _advance(self, weapon, gen):
        try:
            delay = next(gen); weapon.tasks.append((time.time() + delay, gen))
        except StopIteration: pass
        except Exception as e:
            if not weapon.gs2: raise
            self.s.log.append(f"gs2 weapon {weapon.name}: {e!r}")

    def fire(self, index):
        ws = self.firable()
        if not getattr(self.s, "weapons_enabled", True): return None
        if 0 <= index < len(ws): self.run_event(ws[index], "weaponfired"); return ws[index].name
        return None

    def sword_event(self):
        """playershootssword goes to the selected weapon and to weapons that cannot be selected (no weaponfired), not to every weapon:
        the dragon weapons (GreenDragon, UndeadDragon, Syren Song4) share client.dragon and only check that flag, so with the event sent
        to all of them the last one to answer took over (GreenDragon turned into UndeadDragon on the first sword press)."""
        firable = {w.name for w in self.firable()}
        for w in list(self.weapons.values()):
            if w.name in firable and w.name != self.selected: continue
            self.broadcast("playershootssword", only=w.name)

    def broadcast(self, event, chat="", params=(), only=None):
        for w in self.weapons.values():
            if only and w.name.lower() != only.lower(): continue
            handles = w.gs2.has_function("on" + event.lower()) if w.gs2 else event.lower() in client_part(w.script).lower()
            if handles and (not w.name.startswith("-") or event.lower().startswith("action") or w.gs2):
                self.run_event(w, event, chat, params)

    def tick(self, now=None):
        now = now or time.time()
        lvl = self.s.level_name
        if lvl != getattr(self, "_lvl", None):
            first = getattr(self, "_lvl", None) is None; self._lvl = lvl
            if lvl and not first:
                for wp in list(self.weapons.values()):
                    if wp.gs2 and wp.gs2.has_function("onplayerenters"): self.run_event(wp, "playerenters")
        for w in list(self.weapons.values()):
            due = [t for t in w.tasks if t[0] <= now]; w.tasks = [t for t in w.tasks if t[0] > now]
            for _, gen in due: self._advance(w, gen)
            if w.timeout_at is not None and w.timeout_at <= now:
                w.timeout_at = None; self.run_event(w, "timeout")
