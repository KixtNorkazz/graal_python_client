"""A local stand-in for the NPC server: runs the *server part* of GS2 weapons (the text before `//#CLIENTSIDE`) so that
`triggerserver(...)` / `serverFunction(...)` and the staff tools' server commands have something to talk to.

The real gs2emu server of this project has no GS2 NPC server, so this is only used when `enabled` (offline sessions, or `--local-server`).
Server scripts get the server API: `player` (the caller), `findplayer(account)`, `findplayerbycommunityname`, `player.weapons`,
`addweapon` / `removeweapon`, `server.*` variables, `triggerclient(...)` (loopback to `onActionClientSide`), `sendtorc`, `savelog2`, `echo2`, `sendpm`,
and the introspection methods (`type()`, `objectType()`, `getVarNames()` ...). File access stays in `server_files/` (see gs2src.sandbox_path)."""
import os, re, time
import gs2src, gs2npc, gs2sched, weaponlib, weapons
from gs2src import Obj, DictObj, NullObj, num, text, truth

LATENCY = 0.02

def server_part(script):
    """Text before //#CLIENTSIDE ('' when there is no marker: then the script is client-only for us)."""
    m = re.search(r"//#?CLIENTSIDE", script or ""); return script[:m.start()] if m else ""

def server_class_source(name):
    from offline import class_text
    t = class_text(name)
    if t is None: return None
    m = re.search(r"//#?CLIENTSIDE", t); return t[:m.start()] if m else t

def norm(name): return re.sub(r"^[^A-Za-z0-9]+", "", name).lower()

class WeaponRef(Obj):
    objtype = "Weapon"
    def __init__(self, name, image=""): self.name, self.image = name, image
    def has(self, n): return n in ("name", "image")
    def get(self, n): return self.name if n == "name" else self.image if n == "image" else None
    def varnames(self, kind): return ["name", "image"] if kind in ("all", "static") else []

class PlayerSrv(Obj):
    """A player whose client runs in this process (a Session): full access (weapons, triggerclient target, PMs) and the server may move it:
    `x` / `y` are level-local tiles (like GS2), `gmapx` / `gmapy` the gmap cell, `level` warps, `setlevel2(level, x, y)` / `setpos(x, y)`."""
    objtype = "Player"
    SETTABLE = ("x", "y", "gmapx", "gmapy", "level", "chat", "ani", "dir", "avoidplayers")
    def __init__(self, srv, sess): self.srv, self.sess = srv, sess
    @property
    def name(self): return getattr(self.sess, "account_name", "")
    def has(self, n): return n in ("account", "nick", "level", "x", "y", "chat", "weapons", "name", "id", "gmap", "gmapx", "gmapy", "communityname", "ani", "dir", "walking", "avoidplayers")
    def get(self, n):
        s = self.sess
        if n in ("account", "name", "communityname"): return getattr(s, "account_name", "")
        if n == "nick": return str(s.me.get("NICKNAME", getattr(s, "account_name", "")))
        if n == "level": return s.level_name or ""
        if n == "x": return s.pos[0] / 16
        if n == "y": return s.pos[1] / 16
        if n == "gmapx": return float(s.cell[0]) if s.gmap else 0.0
        if n == "gmapy": return float(s.cell[1]) if s.gmap else 0.0
        if n == "chat": return self.srv.chat
        if n == "gmap": return s.gmap or ""
        if n == "ani": return s.me.get("GANI", "")
        if n == "dir": return float(s.me.get("SPRITE", 2) & 3)
        if n == "walking": return 1.0 if s.walking_to() else 0.0
        if n == "avoidplayers": return 1.0 if getattr(s, "avoid_players", True) else 0.0
        if n == "weapons": return [WeaponRef(w.name, w.image) for w in s.runner.weapons.values()]
        if n == "id": return float(s.me.get("ID", 0) or 0)
        return None
    def _tp(self, x, y, cell=None, force=False):
        ok = self.sess.teleport(x, y, cell, check=not force)
        if not ok: self.srv.home.log.append(f"move refused: {self.get('account')} cannot stand at ({x:g}, {y:g}) (wall within 3 tiles)")
        return 1.0 if ok else 0.0
    def set(self, n, v):
        s = self.sess
        if n == "x": self._tp(num(v), s.pos[1] / 16, force=True)
        elif n == "y": self._tp(s.pos[0] / 16, num(v), force=True)
        elif n == "gmapx" and s.gmap: self._tp(s.pos[0] / 16, s.pos[1] / 16, (int(num(v)), s.cell[1]), force=True)
        elif n == "gmapy" and s.gmap: self._tp(s.pos[0] / 16, s.pos[1] / 16, (s.cell[0], int(num(v))), force=True)
        elif n == "level": s.warp(text(v), s.pos[0], s.pos[1])
        elif n == "avoidplayers": s.avoid_players = truth(v)
        elif n == "chat": s.say(text(v))
        elif n == "ani": s.play_gani(text(v), [])
        elif n == "dir": s.me["SPRITE"] = int(num(v)) & 3
    def varnames(self, kind): return ["account", "nick", "level", "x", "y", "gmapx", "gmapy", "chat", "weapons", "gmap", "ani", "dir"] if kind in ("all", "static") else []
    def call(self, n, args):
        s = self.sess
        if n == "addweapon" and args: return self.srv.addweapon(text(args[0]), s)
        if n == "removeweapon" and args: return self.srv.removeweapon(text(args[0]), s)
        if n == "hasweapon" and args: return 1.0 if any(w.name.lower() == text(args[0]).lower() for w in s.runner.weapons.values()) else 0.0
        if n == "setlevel2" and len(args) >= 3: s.warp(text(args[0]), num(args[1]) * 16, num(args[2]) * 16); return 1.0
        if n == "setpos" and len(args) >= 2: return self._tp(num(args[0]), num(args[1]), force=len(args) > 2 and truth(args[2]))
        if n == "walkto" and len(args) >= 2:
            cell = (int(num(args[2])), int(num(args[3]))) if len(args) >= 4 and s.gmap else None
            return 1.0 if s.walk_to(num(args[0]), num(args[1]), cell) else 0.0
        if n == "stopwalk": s.cancel_walk("cancelled"); return 1.0
        if n == "freeze": s.frozen_until = time.time() + (num(args[0]) if args else 1.0); return 1.0
        if n == "sendpm" and args: return self.srv.sendpm(self, text(args[-1]))
        return None

class RemoteSrv(Obj):
    """A player on the real server that has no client in this process: read-only, from the props the real server sent us.
    The game server has no way to move a client that is not ours, so setting its position is logged and ignored."""
    objtype = "Player"
    def __init__(self, srv, pid, props): self.srv, self.pid, self.p = srv, pid, props
    def has(self, n): return n in ("account", "nick", "level", "x", "y", "gmapx", "gmapy", "chat", "name", "id", "weapons")
    def get(self, n):
        p = self.p
        if n in ("account", "name", "communityname"): return p.get("ACCOUNTNAME", "")
        if n == "nick": return p.get("NICKNAME", "")
        if n == "level": return p.get("LEVEL", "")
        if n == "x": return p.get("X2", 0) / 16
        if n == "y": return p.get("Y2", 0) / 16
        if n == "gmapx": return float(p.get("GMAPLEVELX", 0))
        if n == "gmapy": return float(p.get("GMAPLEVELY", 0))
        if n == "chat": return p.get("MESSAGE", "")
        if n == "id": return float(self.pid)
        if n == "weapons": return []
        return None
    def set(self, n, v):
        if n in PlayerSrv.SETTABLE: self.srv.home.log.append(f"cannot move/modify {self.get('account')}: no client of ours is logged in as that player")
    def varnames(self, kind): return ["account", "nick", "level", "x", "y", "gmapx", "gmapy", "chat"] if kind in ("all", "static") else []
    def call(self, n, args):
        if n == "sendpm" and args: return self.srv.sendpm(self, text(args[-1]))
        if n in ("setlevel2", "setpos", "freeze", "addweapon", "removeweapon"): self.set("x", 0); return 0.0
        return None

class NpcSrv(Obj):
    """An NPC of the NPC database (what findnpc / getnpc / npcs return): the NPCs the home client knows from the real server or the level files."""
    objtype = "NPC"
    def __init__(self, srv, nid, n): self.srv, self.nid, self.n = srv, nid, n
    def has(self, k): return k in ("name", "id", "x", "y", "image", "level", "script", "class", "type", "nick", "visible")
    def get(self, k):
        n = self.n
        if k == "name": return n.get("NAME") or n.get("IMAGE") or ""
        if k == "id": return float(n.get("ID", self.nid if isinstance(self.nid, int) else 0) or 0)
        if k == "x": return n.get("X2", 0) / 16
        if k == "y": return n.get("Y2", 0) / 16
        if k == "image": return n.get("IMAGE", "")
        if k == "level": return n.get("LEVEL", self.srv.s.level_name or "")
        if k == "script": return n.get("SCRIPT", "")
        if k in ("class", "type"): return n.get(k.upper(), "")
        if k == "nick": return n.get("NICKNAME", "")
        if k == "visible": return 1.0
        return None
    def set(self, k, v):
        n = self.n
        if k == "x": n["X2"] = int(num(v) * 16)
        elif k == "y": n["Y2"] = int(num(v) * 16)
        elif k == "image": n["IMAGE"] = text(v)
    def varnames(self, kind): return ["name", "id", "x", "y", "image", "level", "class", "type"] if kind in ("all", "static") else []
    def call(self, k, args):
        if k == "setimg" and args: self.n["IMAGE"] = text(args[0])
        return None

class LevelSrv(Obj):
    objtype = "Level"
    def __init__(self, srv, name): self.srv, self.name = srv, name
    def has(self, k): return k in ("name", "gmap", "players", "npcs")
    def get(self, k):
        s = self.srv.home
        if k == "name": return self.name
        if k == "gmap": return s.gmap or ""
        if k == "players": return [p for p in self.srv.all_players() if text(p.get("level")).lower() == self.name.lower()]
        if k == "npcs": return [NpcSrv(self.srv, i, n) for i, n in s.npcs.items() if (n.get("LEVEL") or s.level_name or "").lower() == self.name.lower()]
        return None
    def varnames(self, kind): return ["name", "gmap", "players", "npcs"] if kind in ("all", "static") else []

class ServerScript:
    """One weapon's server part: the task owner for its coroutines."""
    def __init__(self, srv, name, src):
        self.srv, self.name = srv, name; self.tasks = []; self.timeout_at = None
        self.host = ServerHost(self, srv); self.gs2 = gs2src.Interp(self.host, src, server_class_source); self.gs2.this.name = name

    def run(self, fname, params=(), delay=0.0, sender=None):
        """Queue the call (the loopback adds a little latency like a network would: a caller that is about to waitfor must get there first).
        `sender` is the session whose `player` the script sees; it is re-selected on every resume of the coroutine."""
        gen = gs2sched.GenRunner(self._as(self.gs2.call_function(fname, list(params)), sender), self, self.srv.home)
        self.tasks.append((time.time() + delay, gen))

    def _as(self, gen, sender):
        srv = self.srv
        try:
            srv.sender = sender; d = next(gen)
            while True:
                sent = yield d
                srv.sender = sender; d = gen.send(sent)
        except StopIteration: return

class ServerHost:
    PROPS = {"timeout", "screenwidth", "screenheight"}
    def __init__(self, script, srv): self.script, self.srv, self.s, self.chat = script, srv, srv.home, ""
    def global_obj(self, low):
        if low == "player": return self.srv.player
        if low == "server": return DictObj(self.srv.vars)
        if low == "static": return DictObj(self.s.__dict__.setdefault("gs2_static", {}))
        if low in ("players", "allplayers"): return self.srv.all_players()
        if low == "npcs": return [NpcSrv(self.srv, i, n) for i, n in self.s.npcs.items()]
        if low == "thiso": return self.script.gs2.this
        o = self.srv.script_object(low)
        return o if o is not None else (self.s.gui.lookup(low) if False else None)
    def has_prop(self, low): return low in self.PROPS
    def get_prop(self, low): return 640.0 if low == "screenwidth" else 480.0 if low == "screenheight" else None
    def set_prop(self, low, v):
        if low == "timeout": self.script.timeout_at = time.time() + num(v) if num(v) > 0 else None
    def unknown(self, name): self.s.unsupported["server:" + name] = self.s.unsupported.get("server:" + name, 0) + 1
    def wake(self, target, event): self.s.gui.fire_named(target, event)
    def create_object(self, cls, args, parent):
        if cls == "TStaticVar": return DictObj(self.s.__dict__.setdefault("gs2_static_vars", {}).setdefault((text(args[0]) if args else "").lower(), {}))
        return None

    def call(self, name, args, interp):
        srv = self.srv; sc = self.script
        if name == "settimer": sc.timeout_at = time.time() + num(args[0]) if args and num(args[0]) > 0 else None; return None
        if name == "scheduleevent" and len(args) >= 2:
            sc.tasks.append((time.time() + num(args[0]), gs2sched.GenRunner(self._scheduled(interp, text(args[1]), args[2:]), sc, self.s))); return None
        if name == "triggerclient": return srv.trigger_client(args, interp)
        if name in ("findplayer", "findplayerbycommunityname"): return srv.findplayer(text(args[0]) if args else "")
        if name in ("findnpc", "getnpc"): return srv.findnpc(args[0] if args else "")
        if name == "findnpcbyid": return srv.findnpc(args[0] if args else "", by_id=True)
        if name == "findlevel": return LevelSrv(srv, text(args[0]) if args else "")
        if name in ("sendtorc", "echo2"): self.s.log.append("rc: " + " ".join(text(a) for a in args)); return None
        if name == "echo": self.s.log.append("echo: " + " ".join(text(a) for a in args)); return None
        if name == "savelog2" and len(args) >= 2:
            p = gs2src.sandbox_path("logs/" + text(args[0]), create=True)
            if p: open(p, "a", encoding="latin1").write(_fmt_log(args) + "\n")
            return None
        if name == "sendpm":
            tgt = next((o for o in reversed(interp.withs) if isinstance(o, (PlayerSrv, RemoteSrv))), None)
            if len(args) >= 2: tgt = args[0] if isinstance(args[0], (PlayerSrv, RemoteSrv)) else srv.findplayer(text(args[0]))
            return srv.sendpm(tgt or srv.player, text(args[-1])) if args else None
        if name == "fileexists": p = gs2src.sandbox_path(text(args[0])) if args else None; return 1.0 if p and os.path.exists(p) else 0.0
        self.unknown(name); return None

    def _scheduled(self, interp, fname, args):
        yield 0.0
        yield from interp.call_function(fname, args)

def _fmt_log(args):
    fmt = text(args[1]); rest = list(args[2:])
    return gs2src._format(fmt, rest)

class NpcServer:
    """One server for any number of local clients (Sessions): `register()` each client; scripts are attached once per weapon name."""
    def __init__(self, session):
        self.home = session; self.enabled = False; self.scripts = {}; self.vars = {}; self.chat = ""; self.sessions = {}; self.sender = None; self._pl = {}
        self.register(session)

    @property
    def s(self): return self.sender or self.home

    def register(self, session):
        acc = getattr(session, "account_name", ""); self.sessions[acc.lower()] = session
        session.on_walk_done = lambda result, a=acc: self.home.gui.fire_named(a, "WalkDone")
        if session is not self.home: session.npcserver = self; self.enabled = True

    def player_of(self, sess):
        if sess not in self._pl: self._pl[sess] = PlayerSrv(self, sess)
        return self._pl[sess]

    @property
    def player(self): return self.player_of(self.s)

    def all_players(self):
        """Local clients first, then players the home client sees on the real server (read-only)."""
        out = [self.player_of(x) for x in self.sessions.values()]; known = {getattr(x, "account_name", "").lower() for x in self.sessions.values()}
        for pid, p in list(self.home.players.items()):
            acc = str(p.get("ACCOUNTNAME", "")).lower()
            if acc and acc != "(npcserver)" and acc not in known:
                out.append(RemoteSrv(self, pid, p)); known.add(acc)
        return out

    def attach(self, weapon, session=None):
        """Called when a weapon is added: its server part (if any) starts with onCreated (once per weapon name, shared by all clients)."""
        if not self.enabled or weapon.name in self.scripts: return
        src = server_part(weapon.script)
        if not src.strip() or not re.search(r"\bfunction\s+\w+", src): return
        try: sc = ServerScript(self, weapon.name, src)
        except gs2src.Gs2Error: return
        self.scripts[weapon.name] = sc
        if sc.gs2.has_function("oncreated"): sc.run("oncreated", sender=session)

    def detach(self, name): self.scripts.pop(name, None)

    def script_object(self, low):
        for sc in self.scripts.values():
            if norm(sc.name) == low: return sc.gs2.this
        return None

    def trigger_server(self, wname, params, chat="", sender=None):
        """triggerserver("gui", weapon, action, params...): the server part's onActionServerSide(params) (params[0] = action)."""
        sc = self.scripts.get(wname) or next((x for k, x in self.scripts.items() if norm(k) == norm(wname)), None)
        if sc is None: self.home.log.append(f"triggerserver: no server script for {wname}"); return False
        self.chat = chat; sc.run("onactionserverside", params, delay=LATENCY, sender=sender or self.home); return True

    def trigger_client(self, args, interp=None):
        """triggerclient("gui", weapon, params...): the client part's onActionClientSide(params) of the player in `with (...)`, else of the caller."""
        if len(args) < 2: return None
        tgt = next((o for o in reversed(interp.withs) if isinstance(o, (PlayerSrv, RemoteSrv))), None) if interp is not None else None
        sess = tgt.sess if isinstance(tgt, PlayerSrv) else None if tgt is not None else self.s
        if sess is None: self.home.log.append(f"triggerclient: {tgt.get('account')} has no client here"); return None
        target = text(args[1]).lower()
        for w in list(sess.runner.weapons.values()):
            if w.gs2 and norm(w.name) == norm(target) and w.gs2.has_function("onactionclientside"):
                w.host.chat = ""; w.tasks.append((time.time() + LATENCY, gs2sched.GenRunner(w.gs2.call_function("onactionclientside", list(args[2:])), w, sess)))
        return None

    def findplayer(self, acc):
        if not acc: return self.player
        for p in self.all_players():
            if text(p.get("account")).lower() == acc.lower() or text(p.get("nick")).lower() == acc.lower(): return p
        return None

    def findnpc(self, key, by_id=False):
        s = self.home; k = text(key).lower()
        for i, n in s.npcs.items():
            if by_id or k.isdigit():
                if str(n.get("ID", i)) == text(key).split(".")[0]: return NpcSrv(self, i, n)
            elif k in (str(n.get("NAME", "")).lower(), str(n.get("IMAGE", "")).lower()) or (isinstance(i, tuple) and k == f"{i[0]}:{i[1]}".lower()): return NpcSrv(self, i, n)
        return None

    def sendpm(self, target, msg):
        """A real PM through the game server when the target is a player the sending client can see; always logged."""
        sess = self.s; acc = text(target.get("account")); pid = None
        for p, props in sess.players.items():
            if str(props.get("ACCOUNTNAME", "")).lower() == acc.lower(): pid = p
        if isinstance(target, PlayerSrv) and pid is None: pid = target.sess.me.get("ID")
        sess.log.append(f"pm -> {acc}: {msg}")
        if pid is not None and getattr(sess, "conn", None) is not None: sess.send_pm(int(pid), msg); return 1.0
        return 0.0

    def addweapon(self, name, session=None):
        sess = session or self.s; got = weaponlib.find(name)
        if got is None: self.home.log.append(f"addweapon: unknown weapon {name}"); return 0.0
        if got[0] not in sess.runner.weapons: sess.runner.add(got[0], got[1], got[2])
        return 1.0

    def removeweapon(self, name, session=None):
        sess = session or self.s
        for k in [k for k in sess.runner.weapons if k.lower() == name.lower() or norm(k) == norm(name)]: del sess.runner.weapons[k]
        return 1.0

    def tick(self, now=None):
        if not self.enabled: return
        now = now or time.time()
        for sc in list(self.scripts.values()):
            due = [t for t in sc.tasks if t[0] <= now]; sc.tasks = [t for t in sc.tasks if t[0] > now]
            for _, gen in due:
                try: sc.tasks.append((now + next(gen), gen))
                except StopIteration: pass
                except Exception as e: self.home.log.append(f"server {sc.name}: {e!r}")
            if sc.timeout_at is not None and sc.timeout_at <= now and sc.gs2.has_function("ontimeout"):
                sc.timeout_at = None; sc.run("ontimeout", sender=self.home)
        self.sender = None
