"""Live level-NPC scripts (GS1): each NPC keeps its own state (x, y, image, flags, this.* / script variables, timeout, tweens) and
runs events through the same interpreter as the weapons (weapons.parse / run_nodes / yield_command).
Events: created + playerenters when the NPC appears, playerenters again when we re-enter its level, timeout (timeout = secs),
playertouchsme (edge-triggered), playerchats. The visual state is a gs1.Fx, which render.py and collision.py read."""
import re, time
import gs1, weapons, gs2src, gs2npc, gs2sched
from weapons import Ctx, run_nodes, client_part, to_float

_GS2_EVENT = {"created": "oncreated", "timeout": "ontimeout", "playerenters": "onplayerenters", "playertouchsme": "onplayertouchsme",
              "playerchats": "onplayerchats", "movementfinished": "onmovementfinished", "playerleaves": "onplayerleaves"}

ACTIVE_RANGE = 1400
MAX_RUNS_PER_TICK = 24

class NpcInstance:
    is_npc = True
    def __init__(self, rt, nid, n):
        self.rt, self.nid, self.name = rt, nid, str(nid)
        self.script = n.get("SCRIPT", "") or ""; self.image = n.get("IMAGE", "") or ""
        self.src = (n["X2"], n["Y2"]); self.fx = gs1.Fx(self.image, n["X2"] / 16, n["Y2"] / 16)
        self.nodes = weapons.parse(client_part(self.script)); self.low = client_part(self.script).lower(); self.funcs = weapons.collect_funcs(self.nodes)
        sp = "" if gs2npc.is_gs2(self.script) else weapons.server_part(self.script)
        self.snodes = weapons.parse(sp) if sp.strip() else []; self.slow = sp.lower(); self.alllow = self.slow + "\n" + self.low
        self.this = {}; self.tasks = []; self.timeout_at = None; self.touching = False; self.tween = None
        self.cell = (n.get("GMAPLEVELX", 0), n.get("GMAPLEVELY", 0)); self.level = n.get("LEVEL"); self.npc = n; self.gs2 = None
        if gs2npc.is_gs2(self.script):
            self.host = gs2npc.NpcHost(self, rt.s, rt)
            try:
                self.gs2 = gs2src.Interp(self.host, client_part(self.script), gs2npc.class_source); self.gs2.this.name = self.name
                for cls in weapons._server_joins(self.script): self.gs2.join(cls)
            except gs2src.Gs2Error as e: rt.s.log.append(f"gs2 parse {self.name}: {e}"); self.gs2 = None

    def has(self, event):
        if self.gs2: return self.gs2.has_function(_GS2_EVENT.get(event.lower(), "on" + event.lower()))
        return event.lower() in self.low

    def handle(self, name, args, val, txt, ctx):
        fx = self.fx; a = lambda k, d=0.0: to_float(val(k, d))
        if name in ("setimg", "setgif", "setimgpart", "drawoverplayer", "drawunderplayer", "drawaslight", "setzoomeffect", "setcoloreffect",
                    "hide", "show", "showimg", "hideimg", "hideimgs", "changeimgvis", "changeimgcolors", "changeimgzoom", "changeimgpart", "showcharacter",
                    "setcharani", "setcharprop", "setgifpart", "seteffectmode", "changeimgmode", "canbepushed", "canbepulled", "canbecarried", "addtiledef", "addtiledef2", "dontblock", "setshape", "setshape2"):
            if name in ("setimg", "setgif", "setimgpart", "showimg") and args: args = [weapons.unquote(weapons.subst(v, ctx)) if k == 0 or (name == "showimg" and k == 1) else v for k, v in enumerate(args)]
            gs1.apply_visual(fx, name, args, a)
            if name in ("dontblock", "setshape", "setshape2", "hide", "show", "hideimg", "hideimgs"): self.rt.version += 1
            return True
        if name in ("loadmap", "removetiledefs") : return False if name == "loadmap" else True
        if name == "blockagain": fx.noblock = False; self.rt.version += 1; return True
        if name == "move" and len(args) >= 3:
            dur = max(a(2), 0.05); self.tween = (self.rt.s.clock(), dur, fx.x, fx.y, fx.x + a(0), fx.y + a(1)); return True
        if name == "followplayer":
            gx, gy = self.rt._gpos(self); s = self.rt.s; cx, cy = s.cell if s.gmap else (0, 0)
            self.follow = (gx - (cx * 1024 + s.pos[0]), gy - (cy * 1024 + s.pos[1])); return True
        if name == "attachplayertoobj" and len(args) >= 2:
            s = self.rt.s
            if args[1].strip() == "0": s.attached = None
            else:
                tgt = val(1)
                try: tgt = int(to_float(tgt)) if not isinstance(tgt, str) else tgt
                except (TypeError, ValueError): pass
                s.attached = tgt if tgt in s.npcs and tgt else self.nid
            self.rt.version += 1; self.rt._att_last = None; return True
        if name == "detachplayer": self.rt.s.attached = None; self.rt.version += 1; self.rt._att_last = None; return True
        if name == "say":
            m = weapons.subst(",".join(args), ctx).strip(); self.fx.message = "" if m in ("", "0") else m; self.rt.version += 1; return True
        if name in ("setlevel2", "setlevel") and args:
            ctx.s.warp(txt(0), a(1) * 16, a(2) * 16); return True
        if name == "message": ctx.s.say2(weapons.subst(",".join(args), ctx)); return True
        if name in ("timereverywhere", "nofreeze", "canwarp", "canwarp2", "setcharprop2", "toweapons"): return True
        return False

def truth_(v):
    try: return bool(v) and v != 0 and v != ""
    except Exception: return bool(v)

class _Sink:
    """Swallows every attribute access and call (stands in for the parts of a session a look-ahead must not touch)."""
    def __getattr__(self, name): return self
    def __call__(self, *a, **k): return self
    def __iter__(self): return iter(())
    def __bool__(self): return False
    def __len__(self): return 0

def _shadow_session(s, vt, budget=3000):
    """A copy of the session for simulating an NPC script into the future: own copies of the script state, a virtual clock, and no way to send
    packets, play sounds, shoot, put bombs or touch the GUI / weapons / server."""
    import copy
    sh = object.__new__(type(s)); sh.__dict__.update(s.__dict__)
    for k in ("vars", "flags", "arrays", "texts", "imgs", "unsupported", "ani_replace", "me", "tokens", "log", "polys", "players", "weapons", "flag_values"):
        v = getattr(s, k, None)
        if isinstance(v, (dict, list, set)): setattr(sh, k, copy.copy(v))
    for k in ("gs2_client", "gs2_server", "gs2_static", "gs2_static_vars"):
        if k in s.__dict__: setattr(sh, k, copy.deepcopy(s.__dict__[k]))
    sink = _Sink()
    for k in ("proj", "bombs", "gui", "npcserver", "audio", "runner", "walk_task"): setattr(sh, k, sink if k != "walk_task" else None)
    import collision, copy as _copy
    sh.input = _copy.copy(s.input); sh.input.s = sh; sh.input.down = set(s.input.down); sh.input.buttons = set(s.input.buttons)
    sh.coll = collision.Collision()
    sh.local_inventory = True
    sh.send = lambda *a, **k: None; sh.clock = lambda: vt[0]; sh.on_walk_done = None; sh.sim_budget = [budget]
    return sh

class NpcRuntime:
    def __init__(self, session):
        self.s = session; self.inst = {}; self.version = 0; self.errors = 0; self._last = 0.0; self._lvl = None; self._img_size = {}

    def can_move(self, inst):
        """Does this NPC script ever call `move` (GS1 `move` / GS2 `move(...)`)? Needs a blocking shape. Cached."""
        c = getattr(inst, "_can_move", None)
        if c is None: c = inst._can_move = bool(re.search(r"\bmove\b", inst.low)) and bool(inst.fx.shape) and not inst.fx.noblock
        return c

    def can_open(self, inst):
        """A blocking NPC that reacts to a touch (`playertouchsme` / `onPlayerTouchsMe`): a candidate door or gate."""
        if inst.fx.carriable and inst.fx.shape and not inst.fx.noblock: return True
        c = getattr(inst, "_can_open", None)
        if c is None: c = inst._can_open = any(k in inst.low for k in ("playertouchsme", "playerchats", "actiongrab", "actionpull", "actionpush", "actionlift", "washit", "wasexploded", "wasshot")) and bool(inst.fx.shape) and not inst.fx.noblock
        return c

    def _clone(self, inst, nid, n, now, touch=False, event=None, chat="", flags=(), keys=(), inv=None, weapons=(), budget=3000):
        """A copy of one NPC on a shadow session with a virtual clock (list `vt` of one float), ready to be ticked. GS1: this / position / timeout /
        running tween are copied; GS2: the interpreter (its `this` deep-copied, its own host). A running generator (an event that is
        sleeping) cannot be copied, so the rest of such an event is not simulated."""
        import copy
        vt = [now]; sh = _shadow_session(self.s, vt, budget); rt = NpcRuntime(sh); sh.npcrt = rt
        sh.input.down.update(int(k) for k in keys)
        if inv: sh.me.update(inv)
        for w_ in weapons: sh.weapons[sh._wname(w_)] = b""
        for f in flags:
            sh.flags.add(f); sh.__dict__.setdefault("gs2_client", {})[f.lower()] = 1.0
        i2 = copy.copy(inst); i2.rt = rt; i2.fx = copy.copy(inst.fx); i2.fx.shows = {}; i2.fx.tiledefs = list(inst.fx.tiledefs); i2.fx.charprops = dict(inst.fx.charprops)
        i2.slow = ""; i2.this = {k: (list(v) if isinstance(v, list) else v) for k, v in inst.this.items()}; i2.tasks = []; i2.touching = True; i2.timeout_at, i2.tween = inst.timeout_at, inst.tween; i2.npc = dict(n)
        if inst.gs2:
            g = copy.copy(inst.gs2); g.frames = []; g.withs = []; g.joined = set(inst.gs2.joined); g.this = type(inst.gs2.this)(g, inst.gs2.this.name)
            g.this.d = copy.deepcopy(inst.gs2.this.d); i2.gs2 = g; i2.host = gs2npc.NpcHost(i2, sh, rt); g.host = i2.host
        rt.inst = {nid: i2}; rt._lvl = sh.level_name; rt._last = now
        i2.has = (lambda ev, _h=inst.has: False if ev.lower() in ("playertouchsme", "playerenters", "playerchats", "created") else _h(ev))
        if touch: event = "playertouchsme"
        if event:
            try: rt.run(i2, event, chat)
            except Exception: pass
        return vt, rt, i2

    def lookahead(self, nid, now, horizon=40):
        """Where the NPC will be (gmap-global px, one entry per 50 ms) if its script keeps running: a copy of its state is run forward in virtual
        time on a shadow session (timeouts, `move` tweens, `movementfinished`, sleeps), with `random()` at its mean. The real NPC and the real
        session are not touched. Cached for 0.2 s. None if the NPC is unknown."""
        inst = self.inst.get(nid); n = self.s.npcs.get(nid)
        if inst is None or n is None: return None
        stamp = round(now * 5); cached = getattr(inst, "_look", None)
        if cached and cached[0] == stamp and cached[1] == horizon: return cached[2]
        vt, rt, i2 = self._clone(inst, nid, n, now, budget=12000); cx, cy = (n.get("GMAPLEVELX", 0), n.get("GMAPLEVELY", 0)) if self.s.gmap else (0, 0)
        path = []
        for k in range(horizon + 1):
            vt[0] = now + k * 0.05
            try: rt.tick(vt[0])
            except Exception: path = None; break
            path.append((cx * 1024 + i2.fx.x * 16, cy * 1024 + i2.fx.y * 16))
        inst._look = (stamp, horizon, path)
        return path

    def _opened(self, inst, nid, n, now, **kw):
        """Fire an event on a copy (`event` / `chat` / `flags` as for `_clone`) and run it for 4 s: did the NPC get out of the way?"""
        vt, rt, i2 = self._clone(inst, nid, n, now, **kw); x0, y0 = i2.fx.x, i2.fx.y
        try:
            for k in range(61):
                vt[0] = now + k * 0.05; rt.tick(vt[0])
            return abs(i2.fx.x - x0) * 16 + abs(i2.fx.y - y0) * 16 >= 24 or i2.fx.noblock or i2.fx.hidden or not i2.fx.shape
        except Exception: return False

    def opens_on_touch(self, nid, now):
        """Does touching this blocking NPC make it get out of the way (moved 24 px or more, stopped blocking, or hidden within 4 s)? Cached 2 s."""
        inst = self.inst.get(nid); n = self.s.npcs.get(nid)
        if inst is None or n is None or not self.can_open(inst) or "playertouchsme" not in inst.low: return False
        c = getattr(inst, "_opens", None)
        if c and now - c[0] < 2.0: return c[1]
        res = self._opened(inst, nid, n, now, touch=True); inst._opens = (now, res); return res

    CHAT_PATTERNS = (r"strequals\s*\(\s*#c\s*,\s*([^)]+?)\s*\)", r"#c\s*==\s*\"?([^\"&|)]+?)\"?\s*(?:[&|)]|$)", r"startswith\s*\(\s*([^,()]+?)\s*,\s*#c\s*\)",
                     r"player\.chat\s*==\s*\"([^\"]+)\"", r"strequals\s*\(\s*player\.chat\s*,\s*\"([^\"]+)\"", r"player\.chat\.starts\(\s*\"([^\"]+)\"", r"\bchat\s*==\s*\"([^\"]+)\"")
    FLAG_WORDS = {"created", "playerenters", "playertouchsme", "playerchats", "timeout", "movementfinished", "playerleaves", "true", "false", "mousedown", "mouseup", "mousemove",
                  "strequals", "startswith", "random", "int", "abs", "and", "or", "not", "this", "x", "y", "playerx", "playery"}

    def chat_candidates(self, inst):
        """Chat texts the script compares the chat line with (GS1 `strequals(#c,...)`, `startswith(...,#c)`, `#c == ...`; GS2 `player.chat == "..."`)."""
        c = getattr(inst, "_chats", None)
        if c is None:
            src = inst.script; seen = []
            for pat in self.CHAT_PATTERNS:
                for m in re.finditer(pat, src, re.I):
                    t = m.group(1).strip().strip("\"")
                    if t and t not in seen and len(t) < 60 and "#" not in t: seen.append(t)
            c = inst._chats = seen[:6]
        return c

    def flag_candidates(self, inst):
        """Names the script tests in conditions that could be flags: GS1 plain / dotted identifiers inside `if (...)`, GS2 `client.name`."""
        c = getattr(inst, "_flagc", None)
        if c is None:
            names = []
            for cond in re.findall(r"\bif\s*\(([^{;]*)\)", re.sub(r"//[^\n]*", "", inst.script), re.I):
                cond = re.sub(r"(strequals|startswith)\([^()]*\)", " ", cond)
                for w in re.findall(r"(?<![\w.#])([A-Za-z_][\w.]*)", cond):
                    if w.lower() not in self.FLAG_WORDS and not w.lower().startswith(("this.", "player.", "client.", "temp.")) and w not in names and not re.fullmatch(r"\d+", w): names.append(w)
            for m in re.finditer(r"\bclient\.(\w+)", inst.script):
                if m.group(1) not in names: names.append(m.group(1))
            c = inst._flagc = names[:8]
        return c

    def _flag_set(self, name):
        return name in self.s.flags or bool(truth_(self.s.__dict__.get("gs2_client", {}).get(name.lower())))

    ACTIONS = ("grab", "pull", "push", "lift")
    STAT_RES = ((r"playerrupees|playergralats", "GRALATS"), (r"playerbombs", "BOMBS"), (r"playerdarts|playerarrows", "ARROWS"))

    def key_candidates(self, inst):
        """GS1 `keydown(n)` / GS2 `keydown(n)` numbers the script tests (0-3 arrows, 4 A, 5 S, 6 D)."""
        c = getattr(inst, "_keysc", None)
        if c is None: c = inst._keysc = sorted({int(k) for k in re.findall(r"keydown\s*\(\s*(\d)\s*\)", inst.script, re.I)})
        return c

    def item_candidates(self, inst):
        """[(prop, amount)]: inventory thresholds the script compares with (`playerrupees>=10`, `playerbombs>0` ...)."""
        c = getattr(inst, "_itemsc", None)
        if c is None:
            c = []
            for pat, prop in self.STAT_RES:
                for m in re.finditer(r"(?:%s)\s*(>=|=>|>|==|=)\s*(\d+)" % pat, inst.script, re.I):
                    need = int(m.group(2)) + (1 if m.group(1) == ">" else 0)
                    if (prop, need) not in c: c.append((prop, need))
            inst._itemsc = c[:4]
        return inst._itemsc

    def weapon_candidates(self, inst):
        """Weapon names the script asks for with `hasweapon(name)` (literal names only)."""
        c = getattr(inst, "_weaponsc", None)
        if c is None:
            c = []
            for m in re.finditer(r"hasweapon\s*\(\s*\"?([^)\"#]+?)\"?\s*\)", inst.script, re.I):
                if m.group(1) not in c: c.append(m.group(1))
            inst._weaponsc = c[:3]
        return inst._weaponsc

    def action_candidates(self, inst):
        return [a for a in self.ACTIONS if ("action" + a) in inst.alllow or ("onaction" + a) in inst.alllow]

    def door_way(self, nid, now):
        """How to get this blocking NPC out of the way, found by simulation on copies. A trigger (`how`: touch, chat + `text`, action + `name`: the
        grab / pull / push / lift of the player) possibly combined with `flags` (to set first), `keys` (GS1 keydown numbers to hold) and `items`
        ({prop: amount} the inventory must reach). The simplest combination that opens it wins; None if nothing does. Cached 2 s per NPC."""
        inst = self.inst.get(nid); n = self.s.npcs.get(nid)
        if inst is None or n is None or not self.can_open(inst): return None
        if inst.fx.carriable and not inst.fx.carried: return {"how": "carry", "items": {"GLOVEPOWER": 1}}
        s = self.s; sig = (tuple(sorted(s.flags)), s.me.get("GRALATS"), s.me.get("BOMBS"), s.me.get("ARROWS"), tuple(sorted(s.input.down)), len(s.weapons))
        c = getattr(inst, "_way", None)
        if c and c[2] == sig and now - c[0] < 30.0: return c[1]
        triggers = []
        if "playertouchsme" in inst.low: triggers.append(("playertouchsme", "", {"how": "touch"}))
        if "playerchats" in inst.low: triggers += [("playerchats", t, {"how": "chat", "text": t}) for t in self.chat_candidates(inst)]
        triggers += [("action" + a, "", {"how": "action", "name": a}) for a in self.action_candidates(inst)]
        if "washit" in inst.low: triggers.append(("washit", "", {"how": "hit"}))
        if "wasshot" in inst.low: triggers.append(("wasshot", "", {"how": "shot", "items": {"ARROWS": 1}}))
        if "wasexploded" in inst.low: triggers.append(("wasexploded", "", {"how": "bomb", "items": {"BOMBS": 1}}))
        keys = self.key_candidates(inst); items = self.item_candidates(inst); flags = [f for f in self.flag_candidates(inst) if not self._flag_set(f)]
        weapons = [w for w in self.weapon_candidates(inst) if not self.s.has_weapon(w)]
        groups = [g for g in (("keys", keys), ("items", items), ("flags", flags), ("weapons", weapons)) if g[1]]
        def mod_of(sel):
            m = {}
            for name, vals in sel:
                if name == "keys": m["keys"] = list(vals)
                elif name == "items":
                    m["items"] = {}
                    for p, a in vals: m["items"][p] = max(m["items"].get(p, 0), a)
                else: m[name] = list(vals)
            return m
        mods = [{}]
        for name, vals in groups:
            if name == "keys": mods += [{"keys": [k]} for k in vals]
            elif name == "items": mods += [{"items": {p: a}} for p, a in vals]
            else: mods += [{name: [v]} for v in vals]
        import itertools
        for size in range(2, len(groups) + 1):
            mods += [mod_of(sel) for sel in itertools.combinations(groups, size)]
        way = None; tries = 0
        for mod in mods:
            for ev, chat, label in triggers:
                if tries >= 24: break
                tries += 1; inv = {p: max(float(self.s.me.get(p, 0) or 0), a) for p, a in mod.get("items", {}).items()} or None
                if self._opened(inst, nid, n, now, event=ev, chat=chat, flags=mod.get("flags", ()), keys=mod.get("keys", ()), inv=inv, weapons=mod.get("weapons", ()), budget=1200):
                    way = dict(label); way.update({k: v for k, v in mod.items() if v and k != "items"})
                    if label.get("items") or mod.get("items"): way["items"] = {**label.get("items", {}), **mod.get("items", {})}
                    break
            if way: break
        inst._way = (now, way, sig); return way

    SOURCE_RE = re.compile(r"addweapon|player(?:rupees|gralats|bombs|darts|arrows)\s*[-+*/]?=(?!=)", re.I)

    def sources(self, now):
        """NPCs that hand out or sell things, found by simulation on copies (cached 10 s per NPC): [{nid, how, text, name, gain: {prop: amount}, cost: {prop: amount},
        weapons: [names], repeat}]. `gain`/`cost` are the change of the inventory (rupees, bombs, arrows) from one trigger with plenty of rupees; `repeat` says that a
        second trigger gives the same again. Prices are what the script takes, so a shop is an NPC with a cost and a gain / weapon."""
        out = []; s = self.s
        sig = (s.me.get("GRALATS"), s.me.get("BOMBS"), s.me.get("ARROWS"), len(s.weapons))
        for nid, inst in list(self.inst.items()):
            n = s.npcs.get(nid)
            if n is None or not self.SOURCE_RE.search(inst.script): continue
            c = getattr(inst, "_src", None)
            if c and c[2] == sig and now - c[0] < 10.0: out += c[1]; continue
            found = []
            trig = ([("playertouchsme", "", dict(how="touch", text=""))] if "playertouchsme" in inst.alllow else []) + \
                   [("playerchats", t, dict(how="chat", text=t)) for t in self.chat_candidates(inst)] + [("action" + a, "", dict(how="action", text="", name=a)) for a in self.action_candidates(inst)]
            for ev, chat, label in trig[:5]:
                r = self._source_try(inst, nid, n, now, ev, chat)
                if r: d = dict(nid=nid, image=n.get("IMAGE", ""), **label); d.update(r); found.append(d)
                if found: break
            inst._src = (now, found, sig); out += found
        return out

    def _source_try(self, inst, nid, n, now, ev, chat):
        """Fire one trigger on a copy with plenty of rupees; what changed in the inventory / weapons, and whether it changes again the second time."""
        rich = 1000.0; props = ("GRALATS", "BOMBS", "ARROWS")
        try:
            vt, rt, i2 = self._clone(inst, nid, n, now, event=ev, chat=chat, inv={"GRALATS": max(rich, float(self.s.me.get("GRALATS", 0) or 0))}, budget=1500)
            sh = rt.s; base = {p: (rich if p == "GRALATS" else float(self.s.me.get(p, 0) or 0)) for p in props}; w0 = set(self.s.weapons)
            base["GRALATS"] = max(rich, float(self.s.me.get("GRALATS", 0) or 0))
            for k in range(41): vt[0] = now + k * 0.05; rt.tick(vt[0])
            d1 = {p: float(sh.me.get(p, 0) or 0) - base[p] for p in props}; ws = sorted(set(sh.weapons) - w0)
            before = {p: float(sh.me.get(p, 0) or 0) for p in props}
            rt.run(i2, ev, chat)
            for k in range(41): vt[0] = now + 2.0 + k * 0.05; rt.tick(vt[0])
            d2 = {p: float(sh.me.get(p, 0) or 0) - before[p] for p in props}
        except Exception: return None
        gain = {p: v for p, v in d1.items() if v > 0}; cost = {p: -v for p, v in d1.items() if v < 0}
        if not gain and not ws: return None
        repeat = bool(gain) and all(d2.get(p, 0) > 0 for p in gain)
        return dict(gain=gain, cost=cost, weapons=ws, repeat=repeat)

    def flag_setter(self, flag, now):
        """An NPC that sets `flag` when touched or when a chat line is said: (nid, "touch"|"chat", text) or None; found by simulation, cached 5 s."""
        cache = self.__dict__.setdefault("_setters", {}); c = cache.get(flag)
        if c and now - c[0] < 5.0: return c[1]
        found = None; fl = flag.lower()
        for nid, inst in self.inst.items():
            n = self.s.npcs.get(nid)
            if n is None or fl not in inst.script.lower(): continue
            for how, text_ in ([("chat", t) for t in self.chat_candidates(inst)] + ([("touch", "")] if "playertouchsme" in inst.low else [])):
                vt, rt, i2 = self._clone(inst, nid, n, now, event="playertouchsme" if how == "touch" else "playerchats", chat=text_)
                try:
                    for k in range(21): vt[0] = now + k * 0.05; rt.tick(vt[0])
                except Exception: continue
                sh = rt.s
                if flag in sh.flags or truth_(sh.__dict__.get("gs2_client", {}).get(fl)): found = (nid, how, text_); break
            if found: break
        cache[flag] = (now, found); return found

    def doors(self, now, chat=True, flags=True):
        """{nid: way} for every blocking NPC that can be opened: by touch, by a chat line (`chat`), or after setting a flag some setter NPC can set (`flags`)."""
        out = {}; s = self.s; cx, cy = s.cell if s.gmap else (0, 0); mx, my = cx * 1024 + s.pos[0], cy * 1024 + s.pos[1]
        f = getattr(s, "_focus", None)
        x0, y0, x1, y1 = (min(f[0], f[2]) - 500, min(f[1], f[3]) - 500, max(f[0], f[2]) + 500, max(f[1], f[3]) + 500) if f else (mx - 1800, my - 1800, mx + 1800, my + 1800)
        for nid, i in self.inst.items():
            if not self.can_open(i): continue
            rects = s.coll.npc_rects_of(s, nid)
            if rects:
                if not (min(r[0] for r in rects) <= x1 and max(r[0] + r[2] for r in rects) >= x0 and min(r[1] for r in rects) <= y1 and max(r[1] + r[3] for r in rects) >= y0): continue
            else:
                gx, gy = self._gpos(i)
                if not (x0 <= gx <= x1 and y0 <= gy <= y1): continue
            w = self.door_way(nid, now)
            if not w: continue
            if w["how"] == "chat" and not chat: continue
            if (w.get("items") or w.get("weapons")) and self.s.acquire_plan(w.get("items", {}), w.get("weapons", []), now) is None: continue
            if w.get("flags"):
                if not flags or not chat or any(self.flag_setter(f, now) is None for f in w["flags"]): continue
            if (w.get("keys") or w["how"] in ("action", "carry")) and not chat: continue
            out[nid] = w
        return out

    def openers(self, now): return set(self.doors(now))

    def instance(self, nid, n):
        i = self.inst.get(nid)
        if i is not None and (i.script, i.image) == (n.get("SCRIPT", "") or "", n.get("IMAGE", "") or ""):
            if i.src != (n["X2"], n["Y2"]): i.src = (n["X2"], n["Y2"]); i.fx.x, i.fx.y = n["X2"] / 16, n["Y2"] / 16; self.version += 1
            return i
        i = self.inst[nid] = NpcInstance(self, nid, n); self.version += 1
        for ev in ("created", "playerenters"):
            if i.has(ev) or (ev == "created" and not i.gs2 and i.script.strip()): self.run(i, ev)
        i._base = self._snap(i)
        st = self.s.__dict__.get("_npc_saved", {}).get(self.state_key(nid))
        if st: self.apply_state(i, st)
        return i

    @staticmethod
    def state_key(nid): return "|".join(str(p) for p in nid) if isinstance(nid, tuple) else str(nid)

    @staticmethod
    def _json_ok(v):
        import json
        try: json.dumps(v); return True
        except (TypeError, ValueError): return False

    def _snap(self, inst):
        return dict(x=round(inst.fx.x, 4), y=round(inst.fx.y, 4), this={k: v for k, v in inst.this.items() if self._json_ok(v)},
                    gs2={k: v for k, v in inst.gs2.this.d.items() if self._json_ok(v)} if inst.gs2 else {},
                    hidden=inst.fx.hidden, noblock=inst.fx.noblock, message=inst.fx.message)

    def state_of(self, inst):
        """What an NPC remembers beyond what `created` sets up: position, `this` variables (GS1 and GS2), visibility, blocking, speech bubble; None when unchanged."""
        import hashlib, copy
        cur = self._snap(inst)
        if cur == getattr(inst, "_base", None): return None
        cur["h"] = hashlib.md5(inst.script.encode("latin1", "replace")).hexdigest()
        now = self.s.clock()
        if inst.timeout_at is not None: cur["timeout_in"] = round(max(0.0, inst.timeout_at - now), 3)
        if inst.tween:
            t0, dur, x0, y0, x1, y1 = inst.tween; cur["tween"] = [round(max(0.0, t0 + dur - now), 3), dur, x0, y0, x1, y1]
        return copy.deepcopy(cur)

    def apply_state(self, inst, st):
        import hashlib
        if st.get("h") != hashlib.md5(inst.script.encode("latin1", "replace")).hexdigest(): return False
        inst.fx.x, inst.fx.y = st["x"], st["y"]; inst.this.update(st.get("this", {})); inst.fx.hidden = st.get("hidden", False)
        inst.fx.noblock = st.get("noblock", False); inst.fx.message = st.get("message", "")
        if inst.gs2 and st.get("gs2"): inst.gs2.this.d.update(st["gs2"])
        now = self.s.clock()
        if st.get("timeout_in") is not None: inst.timeout_at = now + st["timeout_in"]
        if st.get("tween"):
            left, dur, x0, y0, x1, y1 = st["tween"]; inst.tween = (now - (dur - left), dur, x0, y0, x1, y1)
        self.version += 1; return True

    def save_states(self):
        out = {}
        for nid, inst in self.inst.items():
            st = self.state_of(inst)
            if st: out[self.state_key(nid)] = st
        return out

    def fx(self, nid, n): return self.instance(nid, n).fx

    def run(self, inst, event, chat="", params=()):
        if inst.gs2:
            inst.host.chat = chat; gen = gs2sched.GenRunner(inst.gs2.call_function(_GS2_EVENT.get(event, "on" + event), params), inst, self.s)
        else:
            ctx = Ctx(inst, self.s, event, chat, params); gen = run_nodes(inst.nodes, ctx)
            if inst.snodes and (event in ("playertouchsme", "playerchats") or event.startswith("action")):
                try: inst.tasks.append((self.s.clock(), run_nodes(inst.snodes, Ctx(inst, self.s, event, chat, params))))
                except Exception as e: self.errors += 1; self.s.log.append(f"npc {inst.name} server {event}: {e!r}")
        try: inst.tasks.append((self.s.clock() + next(gen), gen))
        except StopIteration: pass
        except Exception as e: self.errors += 1; self.s.log.append(f"npc {inst.name} {event}: {e!r}")

    def broadcast(self, event, chat="", params=()):
        for i in list(self.inst.values()):
            if i.has(event): self.run(i, event, chat, params)

    def _gpos(self, i): return (i.cell[0] * 1024 + i.fx.x * 16, i.cell[1] * 1024 + i.fx.y * 16)

    def _size(self, i):
        name = i.fx.image
        if i.fx.imgpart: return i.fx.imgpart[3] or 16, i.fx.imgpart[4] or 16
        if not name or name in ("-", "#c#"): return 32, 32
        if name not in self._img_size:
            import render; im = render.load_image(name); self._img_size[name] = im.size if im else (16, 16)
        return self._img_size[name]

    def tick(self, now=None):
        s = self.s; now = now or s.clock(); runs = 0
        if s.level_name != self._lvl:
            first = self._lvl is None; self._lvl = s.level_name
            if not first:
                for i in self.inst.values():
                    if i.level == s.level_name and i.has("playerenters"): self.run(i, "playerenters")
        for nid in [k for k in self.inst if k not in s.npcs]: del self.inst[nid]; self.version += 1
        cx, cy = s.cell if s.gmap else (0, 0); me_x, me_y = cx * 1024 + s.pos[0], cy * 1024 + s.pos[1]
        dt = now - self._last if self._last else 0.0; self._last = now
        at = s.attached
        if at is not None and at in self.inst:
            ai = self.inst[at]; cur = (ai.fx.x * 16, ai.fx.y * 16); last = getattr(self, "_att_last", None)
            if last and last[0] == at and not ai.fx.carried:
                rx, ry = getattr(self, "_att_rem", (0.0, 0.0)); fx_, fy_ = cur[0] - last[1] + rx, cur[1] - last[2] + ry
                dx, dy = int(round(fx_)), int(round(fy_)); self._att_rem = (fx_ - dx, fy_ - dy)
                if dx or dy: s.pos = (s.pos[0] + dx, s.pos[1] + dy); me_x += dx; me_y += dy
            else: self._att_rem = (0.0, 0.0)
            self._att_last = (at,) + cur
        else: self._att_last = None
        for i in list(self.inst.values()):
            gx, gy = self._gpos(i)
            if abs(gx - me_x) > ACTIVE_RANGE or abs(gy - me_y) > ACTIVE_RANGE: continue
            for idx, sh in i.fx.shows.items():
                if "em" in sh: sh["em"].update(dt, (sh["x"] * 16, sh["y"] * 16) if idx < 200 else (sh["x"], sh["y"]))
            if getattr(i, "follow", None):
                icx, icy = i.cell if s.gmap else (0, 0); nx, ny = (me_x + i.follow[0] - icx * 1024) / 16, (me_y + i.follow[1] - icy * 1024) / 16
                if (nx, ny) != (i.fx.x, i.fx.y): i.fx.x, i.fx.y = nx, ny; self.version += 1
            if i.tween:
                t0, dur, x0, y0, x1, y1 = i.tween; f = min(1.0, (now - t0) / dur)
                i.fx.x, i.fx.y = x0 + (x1 - x0) * f, y0 + (y1 - y0) * f; self.version += 1
                if f >= 1.0:
                    i.tween = None
                    if i.has("movementfinished"): self.run(i, "movementfinished")
            due = [t for t in i.tasks if t[0] <= now]; i.tasks = [t for t in i.tasks if t[0] > now]
            for _, gen in due:
                try: i.tasks.append((now + next(gen), gen))
                except StopIteration: pass
                except Exception as e: self.errors += 1; self.s.log.append(f"npc {i.name} task: {e!r}")
            if i.timeout_at is not None and i.timeout_at <= now and runs < MAX_RUNS_PER_TICK:
                i.timeout_at = None; self.run(i, "timeout"); runs += 1
            if i.has("playertouchsme") or "playertouchsme" in i.slow:
                w, h = self._size(i)
                touch = gx - 8 <= me_x + 24 and me_x + 8 <= gx + w and gy - 8 <= me_y + 48 and me_y + 24 <= gy + h
                sig = (tuple(sorted(s.input.down)), tuple(sorted(s.flags)), s.me.get("GRALATS"), s.me.get("BOMBS"), s.me.get("ARROWS"), len(s.weapons))
                if touch and (not i.touching or (getattr(i, "touch_sig", None) != sig and now - getattr(i, "touch_t", -9.0) >= 1.0)): i.touch_t = now; self.run(i, "playertouchsme"); i.touch_sig = (tuple(sorted(s.input.down)), tuple(sorted(s.flags)), s.me.get("GRALATS"), s.me.get("BOMBS"), s.me.get("ARROWS"), len(s.weapons))
                i.touching = touch
