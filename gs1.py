"""A deliberately small GS1 subset interpreter: runs the client-side script of an NPC once (created / playerenters /
timeout fired) and reports its visual effects. Anything it does not know is ignored (and counted in `unknown`)."""
import math, random, re

TRUE_FLAGS = {"created", "playerenters", "timeout"}

def _split_args(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "({": depth += 1
        elif ch in ")}": depth -= 1
        if ch == "," and depth == 0: out.append(cur.strip()); cur = ""
        else: cur += ch
    if cur.strip(): out.append(cur.strip())
    return out

class Fx:
    def __init__(self, image, x, y):
        self.image, self.x, self.y = image, x, y
        self.imgpart = None; self.over = self.under = self.light = False
        self.zoom = 1.0; self.color = None; self.shows = {}; self.hidden = False
        self.charani = None; self.charprops = {}; self.showchar = False; self.unknown = set(); self.tiledefs = []
        self.shape = None; self.noblock = False; self.pushable = False; self.pullable = False; self.carriable = False; self.message = ""; self.carried = False; self.mode = 0

def _eval(expr, env):
    expr = expr.strip()
    if not expr: return 0.0
    def rnd(a=0, b=1): return (a + b) / 2
    names = {"x": env["x"], "y": env["y"], "random": rnd, "int": lambda v: int(v), "sin": math.sin, "cos": math.cos,
             "abs": abs, "playerx": env.get("px", 0), "playery": env.get("py", 0)}
    e = re.sub(r"\b(created|playerenters|timeout)\b", lambda m: "1", expr)
    e = e.replace("||", " or ").replace("&&", " and ")
    e = re.sub(r"(?<![=!<>])!(?!=)", " not ", e)
    if re.search(r"[^0-9a-zA-Z_+\-*/().,<>=! %\s]", e): return 0.0
    try:
        v = eval(e, {"__builtins__": {}}, {**names, **{w: 0 for w in re.findall(r"[a-zA-Z_][a-zA-Z_0-9.]*", e) if w not in names and w not in ("or", "and", "not")}})
        return float(v)
    except Exception:
        return 0.0

def apply_visual(fx, name, args, a):
    """Apply one visual/shape command to an Fx; `a(k, default)` evaluates argument k to a number."""
    if name in ("setimg", "setgif"): fx.image = args[0].strip('"') if args else fx.image
    elif name == "setgifpart" and len(args) >= 5:
        fx.image = args[0].strip('"'); fx.imgpart = (fx.image, int(a(1)), int(a(2)), int(a(3)), int(a(4)))
    elif name == "seteffectmode": fx.mode = int(a(0))
    elif name == "changeimgmode":
        if int(a(0)) in fx.shows: fx.shows[int(a(0))]["normal"] = int(a(1)) == 0
    elif name == "setimgpart": fx.imgpart = (args[0].strip('"'), int(a(1)), int(a(2)), int(a(3)), int(a(4)))
    elif name == "drawoverplayer": fx.over = True
    elif name == "drawunderplayer": fx.under = True
    elif name == "drawaslight": fx.light = True
    elif name == "setzoomeffect": fx.zoom = a(0, 1.0)
    elif name == "setcoloreffect": fx.color = (a(0), a(1), a(2), a(3, 1.0))
    elif name == "hide": fx.hidden = True
    elif name == "show": fx.hidden = False
    elif name == "showimg":
        fx.shows[int(a(0))] = dict(image=args[1].strip('"'), x=a(2), y=a(3), vis=None, color=None, zoom=1.0, part=None)
    elif name == "hideimg": fx.shows.pop(int(a(0)), None)
    elif name == "hideimgs":
        for k in range(int(a(0)), int(a(1)) + 1): fx.shows.pop(k, None)
    elif name == "changeimgvis":
        if int(a(0)) in fx.shows: fx.shows[int(a(0))]["vis"] = int(a(1))
    elif name == "changeimgcolors":
        if int(a(0)) in fx.shows: fx.shows[int(a(0))]["color"] = (a(1), a(2), a(3), a(4, 1.0))
    elif name == "changeimgzoom":
        if int(a(0)) in fx.shows: fx.shows[int(a(0))]["zoom"] = a(1, 1.0)
    elif name == "changeimgpart":
        if int(a(0)) in fx.shows: fx.shows[int(a(0))]["part"] = (int(a(1)), int(a(2)), int(a(3)), int(a(4)))
    elif name == "showcharacter": fx.showchar = True
    elif name == "setcharani": fx.charani = args[0].strip('"') if args else None
    elif name == "setcharprop": fx.charprops[args[0].strip()] = args[1].strip('"') if len(args) > 1 else ""
    elif name in ("addtiledef", "addtiledef2"): fx.tiledefs.append((name, args))
    elif name == "dontblock": fx.noblock = True
    elif name == "setshape" and len(args) >= 3: fx.shape = ("rect", int(a(1)), int(a(2)))
    elif name == "setshape2" and len(args) >= 3:
        w, h = int(a(0)), int(a(1)); types = [int(v) for v in re.findall(r"-?\d+", args[2])]
        if w > 0 and h > 0 and len(types) >= w * h: fx.shape = ("grid", w, h, types[:w * h])
    elif name == "canbepushed": fx.pushable = True
    elif name == "canbepulled": fx.pullable = True
    elif name == "canbecarried": fx.carriable = True
    elif name in ("setshape", "setshape2", "timereverywhere", "sleep", "say2", "timeout", "move",
                  "setlevel2", "setlevel", "toweapons", "setstring", "set", "unset", "if"): pass
    else: fx.unknown.add(name)

def run(script: str, image: str, x: float, y: float, px=0.0, py=0.0) -> Fx:
    fx = Fx(image, x, y)
    body = "\n".join(l for l in script.splitlines() if not l.strip().startswith("//"))
    body = re.sub(r",\s*\{([^{}]*)\}", lambda m: ",[" + re.sub(r"[,\s]+", " ", m.group(1)).strip() + "]", body)
    toks = re.findall(r"\{|\}|;|[^{};]+", body)
    def parse(i):
        stmts = []
        while i < len(toks):
            t = toks[i].strip()
            if t == "}": return stmts, i + 1
            if t in ("", ";"): i += 1; continue
            if t == "{": sub, i = parse(i + 1); stmts.append(("block", sub)); continue
            m = re.match(r"(if|while|for)\s*\((.*)\)\s*(.*)$", t, re.S)
            if m and m.group(1) == "if":
                cond, rest = m.group(2), m.group(3).strip()
                if rest:
                    node = ("if", cond, [("stmt", rest)]); i += 1
                else:
                    i += 1
                    if i < len(toks) and toks[i].strip() == "{":
                        sub, i = parse(i + 1); node = ("if", cond, sub)
                    else: node = ("if", cond, []); 
                stmts.append(node); continue
            if t.startswith("else"):
                rest = t[4:].strip()
                if rest: stmts.append(("else", [("stmt", rest)])); i += 1
                else:
                    i += 1
                    if i < len(toks) and toks[i].strip() == "{": sub, i = parse(i + 1); stmts.append(("else", sub))
                continue
            stmts.append(("stmt", t)); i += 1
        return stmts, i
    tree, _ = parse(0)
    env = {"x": x, "y": y, "px": px, "py": py}

    def exec_stmts(stmts):
        last_if = None
        for s in stmts:
            kind = s[0]
            if kind == "block": exec_stmts(s[1])
            elif kind == "if":
                last_if = bool(_eval(s[1], env)) and not re.search(r"\b(playertouchsme|playerchats|weaponfired|playerhurt|npcwarped|keydown|mousedown)\b", s[1])
                if last_if: exec_stmts(s[2])
            elif kind == "else":
                if last_if is False: exec_stmts(s[1])
            else: command(s[1])

    def command(st):
        st = st.strip()
        m = re.match(r"(\w+)\s*(?:\((.*)\)|\s+(.*))?$", st, re.S)
        asg = re.match(r"(x|y)\s*(\+|-|\*|/)?=\s*(.+)$", st)
        if asg:
            v = _eval(asg.group(3), env); n = asg.group(1); op = asg.group(2)
            env[n] = v if not op else {"+": env[n] + v, "-": env[n] - v, "*": env[n] * v, "/": env[n] / v if v else env[n]}[op]
            return
        if not m: return
        name = m.group(1).lower(); args = _split_args((m.group(2) if m.group(2) is not None else m.group(3)) or "")
        a = lambda k, d=0.0: _eval(args[k], env) if k < len(args) else d
        apply_visual(fx, name, args, a)

    exec_stmts(tree)
    fx.x, fx.y = env["x"], env["y"]
    return fx
