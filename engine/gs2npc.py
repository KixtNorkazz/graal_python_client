"""Host side of the GS2 interpreter for level NPCs: NPC properties (x, y, image, ...), `player` / `client` / `thiso` objects,
`findimg(n)` image objects, timers, and a bridge that passes every other command call to the GS1 implementations
(`weapons.yield_command`) so both languages share one set of effects."""
import re, time
import weapons, particles, gs2sched
from gs2src import Obj, DictObj, NullObj as _GenericNull, num, text, truth
from weapons import Ctx

class NullObj(_GenericNull):
    """Unknown object (e.g. a particle emitter): swallows every call and attribute access."""
    def has(self, name): return True
    def call(self, name, args): return None

class ImgObj(Obj):
    objtype = "Image"
    """findimg(index): the NPC's image slot `index` (<200 level-relative, >=200 screen-relative) = an entry of fx.shows."""
    ATTRS = {"emitter", "image", "x", "y", "zoom", "rotation", "alpha", "red", "green", "blue", "visible", "mode", "layer", "width", "height", "polygon"}
    def __init__(self, host, idx, store=None):
        self.host, self.idx = host, idx; sh = host.fx.shows if store is None else store
        fx = getattr(host, "fx", None); ox, oy = (fx.x, fx.y) if fx is not None and idx < 200 else (0.0, 0.0)
        if idx not in sh: sh[idx] = dict(image="", x=ox, y=oy, vis=None, color=None, zoom=1.0, part=None, normal=True, rot=0.0, col=[1.0, 1.0, 1.0, 1.0])
        self.d = sh[idx]; self.d.setdefault("col", [1.0, 1.0, 1.0, 1.0]); self.d.setdefault("rot", 0.0); self.d.setdefault("normal", True)
        self.d.setdefault("gs2", {})
    def has(self, name): return name in self.ATTRS or name in self.d["gs2"]
    def get(self, name):
        d = self.d
        if name == "emitter":
            if "em" not in d: d["em"] = particles.Emitter()
            return EmitterObj(self.host, d["em"])
        if name == "image": return d["image"]
        if name in ("x", "y"): return d[name]
        if name == "zoom": return d["zoom"]
        if name == "rotation": return d["rot"]
        if name in ("red", "green", "blue", "alpha"): return d["col"]["rgba".index({"red": "r", "green": "g", "blue": "b", "alpha": "a"}[name])]
        if name == "visible": return 0.0 if d.get("vis") == 0 else 1.0
        return d["gs2"].get(name)
    def set(self, name, v):
        d = self.d
        if name == "image": d["image"] = text(v)
        elif name in ("x", "y"): d[name] = num(v)
        elif name == "zoom": d["zoom"] = num(v) or 1.0
        elif name == "rotation": d["rot"] = num(v)
        elif name in ("red", "green", "blue", "alpha"):
            d["col"]["rgba".index({"red": "r", "green": "g", "blue": "b", "alpha": "a"}[name])] = num(v); d["color"] = tuple(d["col"])
        elif name == "mode": d["normal"] = num(v) != 1
        elif name == "visible": d["vis"] = None if truth(v) else 0
        else: d["gs2"][name] = v
        rt = getattr(self.host, "rt", None)
        if rt is not None: rt.version += 1

class ParticleObj(Obj):
    """`emitter.particle`: defaults for new particles."""
    def __init__(self, em): self.em = em
    def has(self, name): return name in self.em.pdef
    def get(self, name): return self.em.pdef.get(name)
    def set(self, name, v): self.em.pdef[name] = text(v) if name == "image" else num(v)

class EmitterObj(Obj):
    def __init__(self, host, em): self.h, self.em = host, em
    def has(self, name): return True
    def get(self, name):
        if name == "particle": return ParticleObj(self.em)
        return self.em.cfg.get(name)
    def set(self, name, v):
        if name == "emissionoffset": self.em.cfg[name] = [num(x) for x in v] if isinstance(v, list) else [0.0, 0.0, 0.0]
        elif name in self.em.cfg: self.em.cfg[name] = num(v)
    def call(self, name, args):
        if name == "emit": self.em.emit()
        elif name in ("addlocalmodifier", "addglobalmodifier", "addemitmodifier") and len(args) >= 7:
            self.em.add_modifier(name[3:-8], text(args[0]), num(args[1]), num(args[2]), text(args[3]), text(args[4]), num(args[5]), num(args[6]))
        return None

class WeaponHost:
    """Host for GS2 weapon scripts (onWeaponFired, onTimeout, onPlayerChats, onAction<Name>): `player`, `client`, `this`, timers and the
    same GS1 bridge as NPCs. No NPC properties / images (weapons draw through showimg-style commands)."""
    def __init__(self, weapon, session):
        self.weapon, self.s, self.chat = weapon, session, ""
        self.objs = {"player": PlayerObj(self), "system": SystemObj(self), "emitter": NullObj()}
        self.client = DictObj(session.__dict__.setdefault("gs2_client", {})); self.server = DictObj(session.__dict__.setdefault("gs2_server", {}))
    def global_obj(self, low):
        if low == "client": return self.client
        if low == "server": return self.server
        if low == "static": return DictObj(self.s.__dict__.setdefault("gs2_static", {}))
        if low == "thiso" and self.weapon.gs2: return self.weapon.gs2.this
        o = self.objs.get(low)
        if o is None: o = self.s.gui.lookup(low)
        return o if o is not None else self.s.runner.script_object(low)

    def create_object(self, cls, args, parent): return self.s.gui.create(cls, args, parent)
    PROPS = {"timeout", "playerx", "playery", "screenwidth", "screenheight", "weathereffectsenabled", "mousex", "mousey", "mousescreenx", "mousescreeny"}
    def has_prop(self, low): return low in self.PROPS
    def get_prop(self, low):
        if low == "playerx": return self.s.pos[0] / 16
        if low == "playery": return self.s.pos[1] / 16
        if low in ("mousex", "mousey"): return self.s.input.world()[0 if low == "mousex" else 1]
        if low in ("mousescreenx", "mousescreeny"): return self.s.input.sx if low == "mousescreenx" else self.s.input.sy
        if low == "screenwidth": return 640.0
        if low == "screenheight": return 480.0
        if low == "weathereffectsenabled": return 1.0
        return None
    def set_prop(self, low, v):
        if low == "timeout": self.weapon.timeout_at = time.time() + num(v) if num(v) > 0 else None
    def unknown(self, name): self.s.unsupported[name] = self.s.unsupported.get(name, 0) + 1
    def wake(self, target, event): self.s.gui.fire_named(target, event)
    def call(self, name, args, interp):
        w = self.weapon
        if name == "findimg": return ImgObj(self, int(num(args[0])) if args else 0, self.s.imgs)
        if name == "keydown": return 1.0 if args and self.s.input.is_down(num(args[0])) else 0.0
        if name == "echo": self.s.log.append("echo: " + " ".join(text(a) for a in args)); return None
        if name == "fileexists": import assets; return 1.0 if args and assets.find(text(args[0])) else 0.0
        if name == "settimer": w.timeout_at = time.time() + num(args[0]) if args and num(args[0]) > 0 else None; return None
        if name == "scheduleevent" and len(args) >= 2:
            w.tasks.append((time.time() + num(args[0]), gs2sched.GenRunner(self._scheduled(interp, text(args[1]), args[2:]), w, self.s))); return None
        if name == "triggerserver" and len(args) >= 3 and self.s.npcserver.enabled:
            self.s.npcserver.trigger_server(text(args[1]), [text(a) if isinstance(a, str) else a for a in args[2:]], self.chat); return None
        if name == "triggerserver" and len(args) >= 3:
            self.s.send_triggeraction(0, 0, 0, ["serverside", text(args[1]), text(args[2])] + [text(a) for a in args[3:]]); return None
        if name in _SESSION_CMDS: return bridge(self.s, w, self.chat, name, args)
        self.unknown(name); return None
    def _scheduled(self, interp, fname, args):
        yield 0.0
        yield from interp.call_function(fname, args)

class PlayerObj(Obj):
    objtype = "Player"
    def __init__(self, host): self.h = host
    def has(self, name): return name in ("x", "y", "chat", "account", "nick", "dir", "level", "ani")
    def get(self, name):
        s = self.h.s
        if name == "x": return s.pos[0] / 16
        if name == "y": return s.pos[1] / 16
        if name == "chat": return self.h.chat
        if name == "account": return getattr(s, "account_name", "")
        if name == "nick": return str(s.me.get("NICKNAME", ""))
        if name == "dir": return float(s.me.get("SPRITE", 2) & 3)
        if name == "level": return s.level_name or ""
        if name == "ani": return s.me.get("GANI", "")
        return None
    def set(self, name, v):
        s = self.h.s
        if name in ("x", "y"):
            x, y = s.pos; v = int(num(v) * 16)
            s.pos = (v, y) if name == "x" else (x, v)
            from graalproto import gline, gchar, enc_pos, PROP_X2, PROP_Y2
            s.send(gline(2, gchar(PROP_X2 if name == "x" else PROP_Y2) + enc_pos(v)))
        elif name == "dir": s.me["SPRITE"] = int(num(v)) & 3
        elif name == "ani": s.play_gani(text(v), [])
    def call(self, name, args):
        if name == "setani" and args: self.h.s.play_gani(text(args[0]), [text(a) for a in args[1:]])
        return None

class NpcObj(Obj):
    objtype = "NPC"
    """`thiso`: the NPC itself as an object."""
    def __init__(self, host): self.h = host
    def has(self, name): return self.h.has_prop(name)
    def get(self, name): return self.h.get_prop(name)
    def set(self, name, v): self.h.set_prop(name, v)

class SystemObj(Obj):
    def __init__(self, host): self.h = host
    def call(self, name, args):
        if name in ("playlevel", "play") and args: self.h.s.play_sound(text(args[0]))
        elif name == "stopsound": self.h.s.stop_sound(text(args[0]) if args else None)
        return None

class NpcHost:
    PROPS = {"x", "y", "image", "rotation", "visible", "nick", "head", "body", "dir", "ani", "zoom", "width", "height", "chat", "level", "timeout", "playerx", "playery", "playerz", "mousex", "mousey", "mousescreenx", "mousescreeny", "screenwidth", "screenheight"}

    def __init__(self, inst, session, rt):
        self.inst, self.s, self.rt, self.fx = inst, session, rt, inst.fx; self.chat = ""
        self.objs = {"player": PlayerObj(self), "thiso": NpcObj(self), "system": SystemObj(self), "emitter": NullObj()}
        self.client = DictObj(session.__dict__.setdefault("gs2_client", {})); self.server = DictObj(session.__dict__.setdefault("gs2_server", {}))
        self.n = inst.npc

    def global_obj(self, low):
        if low == "client": return self.client
        if low == "server": return self.server
        if low == "static": return DictObj(self.s.__dict__.setdefault("gs2_static", {}))
        o = self.objs.get(low)
        if o is None: o = self.s.gui.lookup(low)
        return o if o is not None else self.s.runner.script_object(low)

    def create_object(self, cls, args, parent): return self.s.gui.create(cls, args, parent)

    def has_prop(self, low): return low in self.PROPS
    def get_prop(self, low):
        fx, n = self.fx, self.n
        if low == "x": return fx.x
        if low == "y": return fx.y
        if low == "image": return fx.image
        if low == "rotation": return getattr(fx, "rotation", 0.0)
        if low == "visible": return 0.0 if fx.hidden else 1.0
        if low == "zoom": return fx.zoom
        if low == "nick": return n.get("NICKNAME", "")
        if low == "head": return n.get("HEADIMAGE", "")
        if low == "body": return n.get("BODYIMAGE", "")
        if low == "dir": return float(n.get("SPRITE", 2) & 3)
        if low == "ani": return n.get("GANI", "")
        if low in ("width", "height"):
            w, h = self.rt._size(self.inst); return float(w if low == "width" else h)
        if low == "chat": return self.chat
        if low == "playerx": return self.s.pos[0] / 16
        if low == "playery": return self.s.pos[1] / 16
        if low in ("mousex", "mousey"): return self.s.input.world()[0 if low == "mousex" else 1]
        if low in ("mousescreenx", "mousescreeny"): return self.s.input.sx if low == "mousescreenx" else self.s.input.sy
        if low == "playerz": return 0.0
        if low == "screenwidth": return 640.0
        if low == "screenheight": return 480.0
        if low == "level": return self.inst.level or ""
        return None
    def set_prop(self, low, v):
        fx, n = self.fx, self.n
        if low in ("x", "y"): setattr(fx, low, num(v)); self.rt.version += 1
        elif low == "image": fx.image = text(v)
        elif low == "rotation": fx.rotation = num(v)
        elif low == "visible": fx.hidden = not truth(v); self.rt.version += 1
        elif low == "zoom": fx.zoom = num(v) or 1.0
        elif low == "nick": n["NICKNAME"] = text(v)
        elif low == "head": n["HEADIMAGE"] = text(v)
        elif low == "body": n["BODYIMAGE"] = text(v)
        elif low == "dir": n["SPRITE"] = int(num(v)) & 3
        elif low == "ani": n["GANI"] = text(v)
        elif low == "timeout": self.inst.timeout_at = self.s.clock() + num(v) if num(v) > 0 else None

    def unknown(self, name): self.s.unsupported[name] = self.s.unsupported.get(name, 0) + 1
    def wake(self, target, event): self.s.gui.fire_named(target, event)

    def call(self, name, args, interp):
        inst = self.inst
        if name == "findimg": return ImgObj(self, int(num(args[0])) if args else 0)
        if name == "keydown": return 1.0 if args and self.s.input.is_down(num(args[0])) else 0.0
        if name == "settimer": inst.timeout_at = self.s.clock() + num(args[0]) if args and num(args[0]) > 0 else None; return None
        if name == "scheduleevent" and len(args) >= 2:
            inst.tasks.append((self.s.clock() + num(args[0]), gs2sched.GenRunner(self._scheduled(interp, text(args[1]), args[2:]), inst, self.s))); return None
        if name == "showcharacter": inst.fx.showchar = True; return None
        if name in ("setshape", "setshape2", "setimg", "setimgpart", "setgifpart", "dontblock", "blockagain", "drawoverplayer", "drawunderplayer",
                    "drawaslight", "setzoomeffect", "setcoloreffect", "seteffectmode", "hide", "show", "setcharani", "setcharprop", "addtiledef",
                    "addtiledef2", "removetiledefs", "canbepushed", "canbepulled", "canbecarried", "attachplayertoobj", "detachplayer", "followplayer", "say",
                    "enableweapons", "disableweapons", "hurt", "setplayerdir", "showstats", "hidestats", "showlocal", "noplayerkilling", "puthorse") or name in _SESSION_CMDS:
            return self._gs1(name, args)
        self.unknown(name); return None

    def _scheduled(self, interp, fname, args):
        yield 0.0
        yield from interp.call_function(fname, args)

    def _gs1(self, name, args): return bridge(self.s, self.inst, self.chat, name, args)

def bridge(session, owner, chat, name, args):
    """Run a GS2 command call through the GS1 implementation: `name(a, b, {c, d})` -> `name a,b,{c,d}`."""
    parts = []
    for a in args:
        if isinstance(a, list): parts.append("{" + ",".join(_fmt(x) for x in _flat(a)) + "}")
        else: parts.append(_fmt(a))
    cmd = name + (" " + ",".join(parts) if parts else "")
    try: weapons.yield_command(cmd, Ctx(owner, session, "", chat, ()))
    except Exception as e: session.log.append(f"gs2 {getattr(owner, 'name', '?')} {name}: {e!r}")
    return None

_SESSION_CMDS = {"play", "playlooped", "stopsound", "stopmidi", "seteffect", "setfocus", "resetfocus", "say2", "showtext", "hidetext", "hideimgs",
                 "setlevel2", "triggeraction", "putbomb", "shoot", "loadmap", "enabledefmovement", "disabledefmovement", "freezeplayer",
                 "setplayerprop", "setani", "replaceani", "setskincolor", "setcoatcolor", "setsleevecolor", "setshoecolor", "setbeltcolor",
                 "showpoly", "hidepoly", "message", "move", "tokenize", "setstring", "set", "unset", "showimg", "changeimgvis", "changeimgcolors",
                 "changeimgzoom", "changeimgpart", "hideimg", "putexplosion", "timereverywhere", "noplayerkilling"}

def _flat(a):
    for x in a:
        if isinstance(x, list): yield from _flat(x)
        else: yield x

def _fmt(v):
    if isinstance(v, str): return '"' + v.replace('"', '""') + '"'
    if v is None: return '""'
    return repr(float(v)) if not isinstance(v, bool) else ("1" if v else "0")

_class_cache = {}
def class_source(name):
    """Class file text for join("name"): client part of local_data/scripts/<name>.txt."""
    from offline import class_text
    t = class_text(name)
    return weapons.client_part(t) if t is not None else None

def is_gs2(script):
    return bool(re.search(r"\bfunction\s+on[A-Za-z]\w*\s*\(", weapons.client_part(script or "")))
