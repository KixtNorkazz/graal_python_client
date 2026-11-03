"""Server-less Session: RP server levels and gmaps loaded from .nw files, so the viewer can walk them.

  python3 viewer.py --offline turtlejunction-.gmap [--cell 3,2] [--pos 512,512]
  python3 viewer.py --offline dreamworld-laboopeakbase.nw
"""
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import assets, nwlevel, render
from gclient import Session, Level

CLASS_DIRS = (config.dirs("class_dirs") + [os.path.join(os.path.dirname(os.path.abspath(__file__)), "classes")]
              + config.dirs("server_script_dirs"))
_classes = None
SERVER_CLASS = "//#SERVERCLASS"

def class_text(name):
    """Class file for `join <name>;` (case-insensitive), or None."""
    global _classes
    if _classes is None:
        _classes = {}
        for d in CLASS_DIRS:
            if os.path.isdir(d):
                for f in os.listdir(d):
                    if f.lower().endswith(".txt"): _classes.setdefault(f[:-4].lower(), os.path.join(d, f))
    p = _classes.get(name.lower())
    if p is None:
        norm = lambda n: re.sub(r"[-_ ]", "", n.lower()); want = norm(name)
        p = next((v for k, v in _classes.items() if norm(k) == want), None)
    return open(p, encoding="latin1").read() if p else None

def expand_joins(script, depth=0):
    """What the server does with clientsidejoins: replace `join X;` in the client part by the class's client part."""
    from weapons import client_part
    def rep(m):
        t = class_text(m.group(1)) if depth < 4 else None
        if t is not None and SERVER_CLASS in t: return ""
        return expand_joins(client_part(t), depth + 1) if t is not None else m.group(0)
    if depth: return re.sub(r"\bjoin\s+([\w\-.]+)\s*;", rep, script)
    m = re.search(r"//#?CLIENTSIDE", script)
    head = script[:m.start()] if m else ""
    server_classes = "".join("\n" + class_text(j.group(1)) for j in re.finditer(r"\bjoin\s+([\w\-.]+)\s*;", script) if (class_text(j.group(1)) or "").find(SERVER_CLASS) >= 0)
    joined = "".join("\n" + rep(j) for j in re.finditer(r"\bjoin\s+([\w\-.]+)\s*;", head) if class_text(j.group(1)) is not None)
    if server_classes:
        return (script[:m.start()] if m else script) + server_classes + "\n//#CLIENTSIDE" + re.sub(r"\bjoin\s+([\w\-.]+)\s*;", rep, client_part(script))
    return (script[:m.end()] if m else "") + re.sub(r"\bjoin\s+([\w\-.]+)\s*;", rep, client_part(script)) + joined

class OfflineSession(Session):
    def __init__(self, target, cell=None, pos=None, account="offline"):
        super().__init__(account, "", "222"); self.npcserver.enabled = True; self.local_inventory = True
        self.v = dict(id39=b"", game=b""); self.timers = dict(hb39=1e18, hb24=1e18); self.nw = {}
        self.me.update(GANI="idle", SPRITE=2, NICK=account, ACCOUNT=account, HALFHEARTS=6, FULLHEARTS=3)
        if target.endswith(".gmap"):
            self.gmap = target; rows = self.gmap_rows(); cx, cy = cell or (len(rows[0]) // 2, len(rows) // 2)
            self.map_cell = (cx, cy); self.me["GMAPLEVELX"], self.me["GMAPLEVELY"] = cx, cy; self.level_name = rows[cy][cx]
            self.pos = pos or (512, 512)
        else:
            self.level_name = target; self.pos = pos or (480, 480)
        self.load_level(self.level_name); self.ensure_neighbours(); self.poll()

    STATE_ME = ("GRALATS", "BOMBS", "ARROWS", "HALFHEARTS", "FULLHEARTS", "GLOVEPOWER", "HORSEIMAGE", "SWORDIMAGE", "SHIELDIMAGE")

    def save_state(self, path):
        """Persist what a server would keep: script variables and flags, the inventory props, the weapon list, opened chests, the player's place. JSON."""
        import json
        def js(v):
            try: json.dumps(v); return v
            except TypeError: return None
        d = dict(vars={k: v for k, v in self.vars.items() if js(v) is not None}, flags=sorted(self.flags), weapons=sorted(self.weapons),
                 me={k: self.me[k] for k in self.STATE_ME if k in self.me and js(self.me[k]) is not None},
                 chests={lv: [[c["x"], c["y"]] for c in cs if c.get("opened")] for lv, cs in self.chests.items() if any(c.get("opened") for c in cs)},
                 place=dict(level=self.level_name, cell=list(self.cell) if self.gmap else None, pos=list(self.pos)),
                 horses=[[h[0], h[1], h[2], list(h[3])] for h in self.horses], npcs=self._npc_memory())
        tmp = path + ".tmp"; open(tmp, "w", encoding="utf-8").write(json.dumps(d, indent=1)); os.replace(tmp, path)

    def _npc_memory(self):
        """Saved NPC states of levels that are not loaded now, plus the live ones (an NPC that is back to its initial state drops its old entry)."""
        base = dict(getattr(self, "_npc_saved", {}))
        for nid in self.npcrt.inst: base.pop(self.npcrt.state_key(nid), None)
        base.update(self.npcrt.save_states()); return base

    def load_state(self, path):
        """Restore `save_state` (the place only when it is the level that is loaded now). Returns False when there is no file."""
        import json
        try: d = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError): return False
        self.vars.update(d.get("vars", {})); self.flags |= set(d.get("flags", [])); self.me.update(d.get("me", {}))
        for w in d.get("weapons", []): self.weapons.setdefault(w, b"")
        for lv, spots in d.get("chests", {}).items():
            for c in self.chests.get(lv, []):
                if [c["x"], c["y"]] in spots: c["opened"] = True
        self._opened_chests = d.get("chests", {})
        self.horses[:] = [(h[0], h[1], h[2], tuple(h[3])) for h in d.get("horses", [])] or self.horses
        self._npc_saved = d.get("npcs", {})
        for nid, inst in list(self.npcrt.inst.items()):
            st = self._npc_saved.get(self.npcrt.state_key(nid))
            if st: self.npcrt.apply_state(inst, st)
        pl = d.get("place") or {}
        if pl.get("level") == self.level_name and pl.get("pos"): self.pos = tuple(pl["pos"])
        return True

    def connect(self): pass
    def close(self): pass
    def send(self, line): pass
    def poll(self): self._apply_map(); self.tick_all()
    def pump(self, secs=0.1): self.poll()

    def load_level(self, name):
        if not name or (name in self.levels and self.levels[name].board): return self.levels.get(name)
        p = assets.find(name)
        if not p: self.log.append(f"missing level {name}"); return None
        nw = nwlevel.load_nw(p); self.nw[name] = nw
        lv = Level(name); lv.board = nw.board
        names = self.CHEST_ITEMS
        self.chests[name] = [dict(opened=[c["x"], c["y"]] in getattr(self, "_opened_chests", {}).get(name, []), x=c["x"], y=c["y"], item=names.index(c["item"])) for c in nw.chests if c["item"] in names]
        lv.signs = [(s_["x"], s_["y"], s_["text"]) for s_ in nw.signs]
        lv.links = [[l["level"], l["x"], l["y"], l["w"], l["h"], l["nx"], l["ny"]] for l in nw.links]
        self.levels[name] = lv
        cx, cy = self.cell_of(name)
        for k, n in enumerate(nw.npcs):
            self.npcs[(name, k)] = dict(IMAGE=n["image"], SCRIPT=expand_joins(n["script"]), X2=int(n["x"] * 16), Y2=int(n["y"] * 16),
                                        GMAPLEVELX=cx, GMAPLEVELY=cy, LEVEL=name)
        for k in [k for k in self.npcs if k[0] == name]:
            if k in self.npcs: self.npcrt.fx(k, self.npcs[k])
        return lv

    def cell_of(self, name):
        rows = self.gmap_rows()
        if rows:
            for y, r in enumerate(rows):
                if name in r: return (r.index(name), y)
        return (0, 0)

    def request_level(self, name, modtime=0): self.load_level(name)

    def load_map(self, name): self.pending_map = name

    def _apply_map(self):
        """loadmap <name>: switch from single-level mode to the named .gmap when our level is part of it."""
        name = getattr(self, "pending_map", None); self.pending_map = None
        if not name: return
        gm = name if name.lower().endswith(".gmap") else name + ".gmap"
        if self.gmap and self.gmap.lower() == gm.lower(): return
        if not assets.find(gm): self.log.append(f"loadmap {name}: no such gmap in the backup"); return
        rows = render.read_gmap(gm); where = next(((r.index(self.level_name), y) for y, r in enumerate(rows) if self.level_name in r), None)
        if where is None: self.log.append(f"loadmap {name}: {self.level_name} is not part of it"); return
        self.gmap = gm; self.map_cell = where; self.me["GMAPLEVELX"], self.me["GMAPLEVELY"] = where
        for n in self.npcs.values():
            if n.get("LEVEL"): n["GMAPLEVELX"], n["GMAPLEVELY"] = self.cell_of(n["LEVEL"])
        self.ensure_neighbours()

    def warp(self, level, x_px, y_px):
        self.npcs = {k: v for k, v in self.npcs.items() if False}; self.levels.clear(); self.gmap = None; self.map_cell = None
        self.me.pop("GMAPLEVELX", None); self.me.pop("GMAPLEVELY", None)
        self.pos = (int(x_px) // 8 * 8, int(y_px) // 8 * 8); self.level_name = level
        if self.load_level(level) is None: self.log.append(f"link target {level} not in the backup")
