"""GS2 GUI controls (`new GuiWindowCtrl("Name") { ... }` and friends): object tree, drawing, mouse/keyboard interaction, events.

Scripts create controls with `new Class("Name") { property = value; new Child(...) {...} }`; the name becomes a global variable
(`InputDialog.visible = false`), events call `function Name.onAction() {...}` in any GS2 script and wake `waitfor("Name", "onAction", t)`.
Drawing is a plain 2D look (no Torque skins): windows with a title bar, raised buttons, sunken edit fields. Profile colours
(`fillcolor`, `fontcolor`, `bordercolor` as {r,g,b[,a]}, 0..255) are honoured when a script sets them; everything else is a fixed look,
so this is a functional GUI, not a pixel copy of the real client's. Positions are relative to the parent control, screen = 640x480."""
import re, time
from PIL import Image, ImageDraw, ImageFont
from gs2src import Obj, DictObj, NullObj, num, text, truth
import gs2sched, gs2src

TITLE_H = 18
CLOSE_W = 16

_FONT = None
def font():
    global _FONT
    if _FONT is None:
        try: _FONT = ImageFont.load_default(size=11)
        except Exception: _FONT = ImageFont.load_default()
    return _FONT

class ProfileObj(DictObj):
    objtype = "GuiControlProfile"
    def has(self, name): return True

class GuiCtrl(Obj):
    @property
    def objtype(self): return self.cls
    def varnames(self, kind): return list(self.a) if kind in ("all", "dynamic") else sorted(self.KNOWN) if kind == "edit" else []
    def funcnames(self): return list(self.script.funcs) if self.script is not None else []

    KNOWN = {"scrollpos", "profile", "position", "extent", "text", "visible", "x", "y", "width", "height", "canmove", "canresize", "canclose", "canminimize",
             "canmaximize", "active", "value", "checked", "name", "parent", "horizsizing", "vertsizing", "minextent", "maxlength", "password", "command",
             "altcommand", "tooltip", "opaque", "image", "bitmap", "selected", "enabled", "scrollposition", "readonly", "modal"}

    def __init__(self, gui, cls, name, parent):
        self.gui, self.cls, self.name, self.parent = gui, cls, name, parent; self.children = []
        big = cls == "GuiWindowCtrl"
        self.a = {"position": [0.0, 0.0], "extent": [300.0, 200.0] if big else [100.0, 20.0], "text": "", "visible": 1.0, "active": 1.0, "value": 0.0,
                  "checked": 0.0, "profile": None, "canmove": 1.0 if big else 0.0, "canclose": 1.0 if big else 0.0}
        self.rows = []; self.scroll = 0; self.script = None; self.tasks = []; self.timeout_at = None; self.scroll_pos = [0.0, 0.0]

    def has(self, name): return name in self.KNOWN or name in self.a
    def get(self, name):
        a = self.a
        if name == "x": return a["position"][0]
        if name == "y": return a["position"][1]
        if name == "width": return a["extent"][0]
        if name == "height": return a["extent"][1]
        if name == "name": return self.name
        if name == "parent": return self.parent
        if name == "enabled": return a["active"]
        if name in ("scrollposition", "scrollpos"): return list(self.scroll_pos)
        return a.get(name)
    def set(self, name, v):
        a = self.a
        if name in ("position", "extent"):
            if not isinstance(v, list): return
            vals = [num(x) for x in v]
            while len(vals) < 2: vals.append(0.0)
            a[name] = vals[:2]
        elif name == "x": a["position"][0] = num(v)
        elif name == "y": a["position"][1] = num(v)
        elif name == "width": a["extent"][0] = num(v)
        elif name == "height": a["extent"][1] = num(v)
        elif name == "text": a["text"] = text(v)
        elif name == "visible": a["visible"] = 1.0 if truth(v) else 0.0
        elif name in ("canmove", "canresize", "canclose", "canminimize", "canmaximize", "active", "checked"): a[name] = 1.0 if truth(v) else 0.0
        elif name == "enabled": a["active"] = 1.0 if truth(v) else 0.0
        elif name in ("scrollposition", "scrollpos"):
            if isinstance(v, list) and len(v) >= 2: self.scroll_pos = [num(v[0]), num(v[1])]; self.gui.clamp_scroll(self)
        else: a[name] = v
    def call(self, name, args):
        g = self.gui
        if name == "destroy": g.destroy(self)
        elif name == "bringtofront": g.bring_to_front(self)
        elif self.script is not None and name in self.script.funcs: return gs2src.FuncRef(self.script, name).invoke(args)
        elif name == "join" and args: return self.ensure_script().join(text(args[0]))
        elif name == "hasfunction" and args: return 1.0 if self.script is not None and text(args[0]).lower() in self.script.funcs else 0.0
        elif name == "performclick": g.fire(self, "onAction")
        elif name == "setfocus": g.focus = self if self.cls.endswith("EditCtrl") else g.focus
        elif name in ("type", "objecttype"): return 2.0 if name == "type" else self.cls
        elif name == "addrow" and args: self.rows.append(text(args[-1])); return float(len(self.rows) - 1)
        elif name == "addtext" and args: self.a["text"] = self.a["text"] + text(args[0])
        elif name == "clear": self.rows = []
        elif name == "getselectedtext": return self.rows[int(num(self.a.get("selected", 0)))] if self.rows and 0 <= int(num(self.a.get("selected", 0))) < len(self.rows) else ""
        elif name in ("open", "openatmouse"): self.a["visible"] = 1.0; g.bring_to_front(self)
        elif name == "size": return float(len(self.rows))
        elif name == "scrolltobottom": s = self if self.cls == "GuiScrollCtrl" else self.nearest_scroll(); s and g.scroll_to(s, 1e9)
        elif name == "scrollto" and len(args) >= 2: s = self if self.cls == "GuiScrollCtrl" else self.nearest_scroll(); s and (s.scroll_pos.__setitem__(0, num(args[0])), g.scroll_to(s, num(args[1])))
        elif name == "scrolltotop": s = self if self.cls == "GuiScrollCtrl" else self.nearest_scroll(); s and g.scroll_to(s, 0)
        return None

    def ensure_script(self):
        """The control's own script (classes joined with `this.join("class")` run here, with the control as `this`)."""
        if self.script is None:
            import gs2npc
            self.script = gs2src.Interp(CtrlHost(self), "", gs2npc.class_source, this=self)
        return self.script

    def abs_pos(self):
        x, y = self.a["position"]; p = self.parent
        while p is not None:
            x += p.a["position"][0]; y += p.a["position"][1]
            if p.cls == "GuiScrollCtrl": x -= p.scroll_pos[0]; y -= p.scroll_pos[1]
            p = p.parent
        return x, y
    def nearest_scroll(self):
        p = self.parent
        while p is not None and p.cls != "GuiScrollCtrl": p = p.parent
        return p
    def shown(self):
        c = self
        while c is not None:
            if not truth(c.a["visible"]): return False
            c = c.parent
        return True
    def box(self):
        x, y = self.abs_pos(); return x, y, x + self.a["extent"][0], y + self.a["extent"][1]

class CtrlHost:
    """Host of a control's own script: properties are the control's attributes; commands go through the GS1 bridge."""
    def __init__(self, ctrl): self.c = ctrl; self.s = ctrl.gui.s; self.chat = ""
    def global_obj(self, low):
        import gs2npc
        if low == "player": return gs2npc.PlayerObj(self)
        if low == "client": return DictObj(self.s.__dict__.setdefault("gs2_client", {}))
        if low == "server": return DictObj(self.s.__dict__.setdefault("gs2_server", {}))
        if low == "static": return DictObj(self.s.__dict__.setdefault("gs2_static", {}))
        o = self.c.gui.lookup(low)
        return o if o is not None else self.s.runner.script_object(low)
    def has_prop(self, low): return low in ("timeout", "screenwidth", "screenheight") or self.c.has(low)
    def get_prop(self, low):
        if low == "screenwidth": return 640.0
        if low == "screenheight": return 480.0
        return self.c.get(low)
    def set_prop(self, low, v):
        if low == "timeout": self.c.timeout_at = time.time() + num(v) if num(v) > 0 else None
        else: self.c.set(low, v)
    def unknown(self, name): self.s.unsupported[name] = self.s.unsupported.get(name, 0) + 1
    def wake(self, target, event): self.s.gui.fire_named(target, event)
    def create_object(self, cls, args, parent): return self.c.gui.create(cls, args, parent)
    def call(self, name, args, interp):
        import gs2npc
        if name == "settimer": self.c.timeout_at = time.time() + num(args[0]) if args and num(args[0]) > 0 else None; return None
        if name == "keydown": return 1.0 if args and self.s.input.is_down(num(args[0])) else 0.0
        if name in gs2npc._SESSION_CMDS: return gs2npc.bridge(self.s, self.c, "", name, args)
        self.unknown(name); return None

class Gui:
    BUTTONISH = ("GuiButtonCtrl", "GuiButtonBaseCtrl", "GuiBitmapButtonCtrl")
    def __init__(self, session):
        self.s = session; self.objs = {}; self.roots = []; self.profiles = {}; self.focus = None; self.waiters = []
        self.pressed = None; self.drag = None; self.counter = 0; self.broken = set()

    def create(self, cls, args, parent):
        """new Class("Name")  ->  GuiCtrl / ProfileObj registered under its name; non-GUI classes return None."""
        name = text(args[0]) if args else ""
        if cls == "TStaticVar":
            return DictObj(self.s.__dict__.setdefault("gs2_static_vars", {}).setdefault(name.lower(), {}))
        if cls.endswith("Profile"):
            p = ProfileObj(); self.profiles[name.lower()] = p; return p
        if not cls.startswith("Gui"): return None
        self.counter += 1; name = name or f"{cls}_{self.counter}"
        old = self.objs.get(name.lower())
        if old is not None: self.destroy(old)
        c = GuiCtrl(self, cls, name, parent if isinstance(parent, GuiCtrl) else None)
        (c.parent.children if c.parent else self.roots).append(c); self.objs[name.lower()] = c
        return c

    def lookup(self, low):
        c = self.objs.get(low)
        if c is not None: return c
        p = self.profiles.get(low)
        if p is not None: return p
        if low.endswith("profile"): p = self.profiles[low] = ProfileObj(); return p
        return None

    def destroy(self, c):
        for ch in list(c.children): self.destroy(ch)
        (c.parent.children if c.parent else self.roots)[:] = [x for x in (c.parent.children if c.parent else self.roots) if x is not c]
        if self.objs.get(c.name.lower()) is c: del self.objs[c.name.lower()]
        if self.focus is c: self.focus = None
        if self.pressed is c: self.pressed = None

    def bring_to_front(self, c):
        while c.parent is not None: c = c.parent
        if c in self.roots: self.roots.remove(c); self.roots.append(c)

    def capturing(self): return self.focus is not None
    def visible_any(self): return any(r.shown() for r in self.roots)

    def scripts(self):
        for w in self.s.runner.weapons.values():
            if w.gs2: yield w
        for i in self.s.npcrt.inst.values():
            if i.gs2: yield i

    def fire(self, c, event, args=()):
        key = f"{c.name.lower()}.{event.lower()}"
        for owner in list(self.scripts()):
            if owner.gs2.has_function(key):
                owner.tasks.append((0.0, gs2sched.GenRunner(owner.gs2.call_function(key, list(args)), owner, self.s)))
        for w in [w for w in self.waiters if w.target == c.name.lower() and w.event == event.lower()]:
            w.fired = True
            if w.runner: w.runner.wake()

    def tick(self, now=None):
        """Control scripts: onTimeout (setTimer / timeout =) and suspended events."""
        now = now or time.time()
        for c in list(self.objs.values()):
            if c.script is None: continue
            due = [t for t in c.tasks if t[0] <= now]; c.tasks = [t for t in c.tasks if t[0] > now]
            for _, gen in due:
                try: c.tasks.append((now + next(gen), gen))
                except StopIteration: pass
                except Exception as e: self.s.log.append(f"gui script {c.name}: {e!r}")
            if c.timeout_at is not None and c.timeout_at <= now and c.script.has_function("ontimeout"):
                c.timeout_at = None; gen = gs2sched.GenRunner(c.script.call_function("ontimeout"), c, self.s)
                try: c.tasks.append((now + next(gen), gen))
                except StopIteration: pass
                except Exception as e: self.s.log.append(f"gui script {c.name}: {e!r}")

    def fire_named(self, target, event):
        """A script's trigger("Event") on object `target`: wake the waitfor(target, "Event", ...) callers."""
        for w in [w for w in self.waiters if w.target == target.lower() and w.event == event.lower()]:
            w.fired = True
            if w.runner: w.runner.wake()

    def unwait(self, w):
        if w in self.waiters: self.waiters.remove(w)

    BAR_W = 12

    def content_size(self, c):
        w = h = 0.0
        for ch in c.children:
            if not truth(ch.a["visible"]): continue
            cw, chh = ch.a["extent"]; chh = max(chh, ch.a.get("_texth", 0.0))
            w = max(w, ch.a["position"][0] + cw); h = max(h, ch.a["position"][1] + chh)
        return w, h

    def max_scroll(self, c):
        cw, chh = self.content_size(c); return max(0.0, chh - c.a["extent"][1]), max(0.0, cw - c.a["extent"][0])

    def bar_visible(self, c):
        mode = text(c.a.get("vscrollbar", "dynamic")).lower()
        return mode == "alwayson" or (mode != "alwaysoff" and self.max_scroll(c)[0] > 0)

    def clamp_scroll(self, c):
        my, mx = self.max_scroll(c); c.scroll_pos[1] = max(0.0, min(my, c.scroll_pos[1])); c.scroll_pos[0] = max(0.0, min(mx, c.scroll_pos[0]))

    def scroll_to(self, c, y): c.scroll_pos[1] = y; self.clamp_scroll(c)

    def thumb(self, c):
        """(top, height) of the scrollbar thumb relative to the scroll control, or None."""
        my = self.max_scroll(c)[0]; vh = c.a["extent"][1]
        if my <= 0: return None
        th = max(16.0, vh * vh / (vh + my)); return (vh - th) * (c.scroll_pos[1] / my), th

    def wheel(self, x, y, dy):
        """Mouse wheel (dy > 0 = up) over a scroll control (or a child of one): scroll it. Returns True if used."""
        h = self.hit(x, y)
        while h is not None and h.cls not in ("GuiScrollCtrl", "GuiTextListCtrl"): h = h.parent
        if h is None: return False
        if h.cls == "GuiTextListCtrl": h.scroll_pos[1] = max(0.0, min(max(0, len(h.rows) - 1) * 12.0, h.scroll_pos[1] - dy * 12)); return True
        h.scroll_pos[1] -= dy * 24; self.clamp_scroll(h); return True

    def hit(self, x, y):
        def walk(c):
            if not truth(c.a["visible"]): return None
            x0, y0, x1, y1 = c.box()
            if c.cls == "GuiScrollCtrl":
                if not (x0 <= x < x1 and y0 <= y < y1): return None
                if self.bar_visible(c) and x >= x1 - self.BAR_W: return c
            for ch in reversed(c.children):
                r = walk(ch)
                if r is not None: return r
            return c if x0 <= x < x1 and y0 <= y < y1 else None
        for r in reversed(self.roots):
            h = walk(r)
            if h is not None: return h
        return None

    def mouse(self, kind, button, x, y):
        """kind 'down'|'up'|'move'. Returns True when the GUI used the event (the game must not see it)."""
        if kind == "move":
            if self.drag:
                if self.drag[0] == "sb":
                    _, c, grab = self.drag; my = self.max_scroll(c)[0]; th = self.thumb(c); track = c.a["extent"][1] - (th[1] if th else 16.0)
                    if track > 0: c.scroll_pos[1] = (y - c.box()[1] - grab) / track * my; self.clamp_scroll(c)
                    return True
                _, c, ox, oy = self.drag; px, py = (c.parent.abs_pos() if c.parent else (0, 0)); c.a["position"] = [x - ox - px, y - oy - py]; return True
            return self.hit(x, y) is not None
        h = self.hit(x, y)
        if kind == "down":
            if h is None: self.focus = None; return False
            root = h
            while root.parent is not None: root = root.parent
            self.bring_to_front(root)
            if h.cls.endswith("EditCtrl"): self.focus = h
            else: self.focus = None
            if h.cls == "GuiScrollCtrl" and self.bar_visible(h) and x >= h.box()[2] - self.BAR_W:
                th = self.thumb(h); ty = h.box()[1] + (th[0] if th else 0)
                if th and ty <= y < ty + th[1]: self.drag = ("sb", h, y - ty)
                else: h.scroll_pos[1] += (-1 if y < ty else 1) * h.a["extent"][1] * 0.9; self.clamp_scroll(h)
                return True
            if h.cls == "GuiWindowCtrl":
                x0, y0, x1, y1 = h.box()
                if truth(h.a["canclose"]) and y < y0 + TITLE_H and x >= x1 - CLOSE_W: h.a["visible"] = 0.0; self.fire(h, "onClose"); return True
                if truth(h.a["canmove"]) and y < y0 + TITLE_H: self.drag = ("win", h, x - x0, y - y0)
            elif h.cls in self.BUTTONISH: self.pressed = h
            elif h.cls == "GuiCheckBoxCtrl": h.a["checked"] = 0.0 if truth(h.a["checked"]) else 1.0; self.fire(h, "onAction")
            return True
        if kind == "up":
            used = self.drag is not None or self.pressed is not None
            self.drag = None
            if self.pressed is not None:
                p, self.pressed = self.pressed, None
                if h is p and truth(p.a["active"]): self.fire(p, "onAction")
            return used or h is not None
        return False

    def key(self, sym, down):
        """Keys while an edit field has focus: Backspace / Return / Escape. Returns True if consumed."""
        f = self.focus
        if f is None: return False
        if down:
            if sym == 8: f.a["text"] = f.a["text"][:-1]; self.fire(f, "onChange")
            elif sym == 13:
                self.fire(f, "onReturn", [f.a["text"]])
                if f.cls in ("GuiTextEditCtrl", "GuiMLTextEditCtrl") and not self._has_ret(f): self.fire(f, "onAction", [f.a["text"]])
            elif sym == 27: self.focus = None
        return True

    def _has_ret(self, f): return any(o.gs2.has_function(f"{f.name.lower()}.onreturn") for o in self.scripts())

    def typed(self, s):
        f = self.focus
        if f is None: return False
        mx = int(num(f.a.get("maxlength", 0))) or 255
        if truth(f.a.get("readonly")): return True
        f.a["text"] = (f.a["text"] + s)[:mx]; self.fire(f, "onChange"); return True

    def render(self, canvas, now=None):
        if not self.roots: return
        d = ImageDraw.Draw(canvas, "RGBA"); now = now or time.time()
        for r in list(self.roots):
            try:
                a = num(r.a.get("alpha", 1.0)) if "alpha" in r.a else 1.0
                if a >= 0.999: self._draw(canvas, d, r, now)
                elif a > 0.0:
                    lay = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); self._draw(lay, ImageDraw.Draw(lay, "RGBA"), r, now)
                    lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a))); canvas.alpha_composite(lay)
            except Exception as e:
                if r.name not in self.broken: self.broken.add(r.name); self.s.log.append(f"gui draw {r.name}: {e!r}")

    def _color(self, c, key, default):
        p = c.a.get("profile")
        if isinstance(p, ProfileObj):
            v = p.d.get(key)
            if isinstance(v, list) and len(v) >= 3: return tuple(int(num(x)) for x in v[:4]) if len(v) >= 4 else tuple(int(num(x)) for x in v[:3]) + (255,)
        return default

    def _draw(self, canvas, d, c, now, off=(0, 0)):
        if not truth(c.a["visible"]): return
        x0, y0, x1, y1 = [int(v) for v in c.box()]; x0 -= off[0]; x1 -= off[0]; y0 -= off[1]; y1 -= off[1]; f = font(); t = c.a["text"]
        if c.cls == "GuiWindowCtrl":
            d.rectangle((x0, y0, x1, y1), fill=self._color(c, "fillcolor", (212, 208, 200, 255)), outline=(40, 40, 40, 255))
            d.rectangle((x0 + 1, y0 + 1, x1 - 1, y0 + TITLE_H), fill=(10, 36, 106, 255)); d.text((x0 + 6, y0 + 4), t, font=f, fill=(255, 255, 255, 255))
            if truth(c.a["canclose"]): d.rectangle((x1 - CLOSE_W, y0 + 2, x1 - 3, y0 + TITLE_H - 2), fill=(200, 60, 50, 255)); d.text((x1 - 12, y0 + 3), "x", font=f, fill=(255, 255, 255, 255))
        elif c.cls in self.BUTTONISH:
            down = self.pressed is c
            d.rectangle((x0, y0, x1, y1), fill=(190, 186, 178, 255) if down else (212, 208, 200, 255), outline=(30, 30, 30, 255))
            d.line((x0 + 1, y0 + 1, x1 - 1, y0 + 1), fill=(120, 120, 120, 255) if down else (255, 255, 255, 255)); d.line((x0 + 1, y0 + 1, x0 + 1, y1 - 1), fill=(120, 120, 120, 255) if down else (255, 255, 255, 255))
            tw = d.textlength(t, font=f); d.text((x0 + (x1 - x0 - tw) / 2 + (1 if down else 0), y0 + (y1 - y0 - 11) / 2 + (1 if down else 0)), t, font=f,
                                                  fill=self._color(c, "fontcolor", (0, 0, 0, 255)) if truth(c.a["active"]) else (130, 130, 130, 255))
        elif c.cls in ("GuiTextEditCtrl", "GuiMLTextEditCtrl"):
            d.rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 255), outline=(60, 60, 60, 255))
            shown = ("*" * len(t)) if truth(c.a.get("password")) else t; caret = "|" if self.focus is c and int(now * 2) % 2 == 0 else ""
            while shown and d.textlength(shown + caret, font=f) > (x1 - x0 - 6): shown = shown[1:]
            d.text((x0 + 3, y0 + (y1 - y0 - 11) / 2), shown + caret, font=f, fill=(0, 0, 0, 255))
        elif c.cls == "GuiTextCtrl":
            d.text((x0, y0 + 2), t, font=f, fill=self._color(c, "fontcolor", (0, 0, 0, 255)))
        elif c.cls == "GuiMLTextCtrl":
            y = y0; t = re.sub(r"<(?!br)[^>]*>", "", t)
            for para in t.replace("<br>", "\n").replace("\r", "").split("\n"):
                line = ""
                for w in para.split(" "):
                    trial = (line + " " + w).strip()
                    if d.textlength(trial, font=f) > (x1 - x0) and line: d.text((x0, y), line, font=f, fill=(0, 0, 0, 255)); y += 12; line = w
                    else: line = trial
                d.text((x0, y), line, font=f, fill=(0, 0, 0, 255)); y += 12
            c.a["_texth"] = float(y - y0)
        elif c.cls == "GuiCheckBoxCtrl":
            d.rectangle((x0, y0 + 2, x0 + 11, y0 + 13), fill=(255, 255, 255, 255), outline=(60, 60, 60, 255))
            if truth(c.a["checked"]): d.line((x0 + 2, y0 + 7, x0 + 5, y0 + 11), fill=(0, 0, 0, 255), width=2); d.line((x0 + 5, y0 + 11, x0 + 10, y0 + 3), fill=(0, 0, 0, 255), width=2)
            d.text((x0 + 16, y0 + 2), t, font=f, fill=(0, 0, 0, 255))
        elif c.cls == "GuiPopUpMenuCtrl":
            d.rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 255), outline=(60, 60, 60, 255)); d.text((x0 + 3, y0 + 4), t or (c.rows[0] if c.rows else ""), font=f, fill=(0, 0, 0, 255))
            d.polygon([(x1 - 12, y0 + 7), (x1 - 4, y0 + 7), (x1 - 8, y0 + 12)], fill=(0, 0, 0, 255))
        elif c.cls == "GuiProgressCtrl":
            d.rectangle((x0, y0, x1, y1), fill=(230, 230, 230, 255), outline=(60, 60, 60, 255)); w = int((x1 - x0 - 2) * max(0.0, min(1.0, num(c.a["value"]))))
            d.rectangle((x0 + 1, y0 + 1, x0 + 1 + w, y1 - 1), fill=(60, 130, 220, 255))
        elif c.cls == "GuiSliderCtrl":
            d.line((x0, (y0 + y1) // 2, x1, (y0 + y1) // 2), fill=(60, 60, 60, 255)); kx = x0 + int((x1 - x0) * max(0.0, min(1.0, num(c.a["value"]))))
            d.rectangle((kx - 3, y0 + 2, kx + 3, y1 - 2), fill=(212, 208, 200, 255), outline=(40, 40, 40, 255))
        elif c.cls == "GuiTextListCtrl":
            d.rectangle((x0, y0, x1, y1), fill=(255, 255, 255, 255), outline=(60, 60, 60, 255))
            first = int(c.scroll_pos[1] // 12)
            for k, row in enumerate(c.rows[first:first + max(1, int((y1 - y0) // 12))]): d.text((x0 + 3, y0 + 2 + k * 12), row, font=f, fill=(0, 0, 0, 255))
        elif c.cls in ("GuiScrollCtrl", "GuiTreeViewCtrl", "GuiContextMenuCtrl"):
            d.rectangle((x0, y0, x1, y1), fill=self._color(c, "fillcolor", (255, 255, 255, 255)) if c.cls != "GuiScrollCtrl" else (245, 245, 245, 255), outline=(60, 60, 60, 255))
        else:
            col = self._color(c, "fillcolor", None)
            if col: d.rectangle((x0, y0, x1, y1), fill=col)
            if c.cls == "GuiControl" and c.a["profile"] is not None and "frame" in str(getattr(c.a["profile"], "d", "")).lower(): d.rectangle((x0, y0, x1, y1), outline=(120, 120, 120, 255))
        if c.cls == "GuiScrollCtrl":
            bx, by, _, _ = c.box(); w, h = max(1, x1 - x0), max(1, y1 - y0); self.clamp_scroll(c)
            tile = Image.new("RGBA", (w, h), (0, 0, 0, 0)); td = ImageDraw.Draw(tile, "RGBA")
            for ch in c.children: self._draw(tile, td, ch, now, (int(bx), int(by)))
            _blit(canvas, tile, x0, y0)
            th = self.thumb(c) if self.bar_visible(c) else None
            if self.bar_visible(c):
                d.rectangle((x1 - self.BAR_W, y0, x1, y1), fill=(225, 225, 225, 255), outline=(120, 120, 120, 255))
                if th: d.rectangle((x1 - self.BAR_W + 1, y0 + th[0], x1 - 1, y0 + th[0] + th[1]), fill=(170, 170, 175, 255), outline=(70, 70, 70, 255))
        else:
            for ch in c.children: self._draw(canvas, d, ch, now, off)


def _blit(canvas, tile, x, y):
    """alpha_composite that tolerates negative / out-of-range destinations."""
    sx, sy = max(0, -x), max(0, -y); dx, dy = max(0, x), max(0, y)
    w, h = min(tile.width - sx, canvas.width - dx), min(tile.height - sy, canvas.height - dy)
    if w > 0 and h > 0: canvas.alpha_composite(tile.crop((sx, sy, sx + w, sy + h)), (dx, dy))
