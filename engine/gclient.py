"""Graal client session: logs in, keeps a model of the world (levels, NPCs, players, chat) and sends actions."""
import math, os, random, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graalproto import *
import leveldoc
from props import parse_npc, parse_player, Reader
import enums
from minclient import Conn, VERSIONS


class Level:
    def __init__(self, name): self.name, self.board, self.links, self.modtime, self.version = name, None, [], 0, 0; self.signs = []; self.meta = None; self.meta_try = 0.0

    def set_tiles(self, x, y, w, h, tiles):
        """Apply a rectangular board change (tiles = list of 16-bit tile indices, row-major) and bump the render version."""
        if self.board is None: return
        if not isinstance(self.board, bytearray): self.board = bytearray(self.board)
        for j in range(h):
            for i in range(w):
                tx, ty = x + i, y + j
                if 0 <= tx < 64 and 0 <= ty < 64 and j * w + i < len(tiles):
                    t = tiles[j * w + i]; o = 2 * (ty * 64 + tx); self.board[o] = t & 0xFF; self.board[o + 1] = t >> 8
        self.version += 1

    def tile(self, x, y):
        i = 2 * (y * 64 + x); return self.board[i] | (self.board[i + 1] << 8)


import collision, gani as ganimod
from weapons import WeaponRunner, _stat

def _stat_sword(s): return _stat(s, "playerswordpower")
from npcrt import NpcRuntime
from projectiles import Projectiles
from bombs import Bombs
from inputs import Input
import pathing
from gui import Gui
from npcserver import NpcServer

ITEM_LIFETIME = 8.2

class Session:
    def __init__(self, account, password, version="222", listserver=("127.0.0.1", 9111), game_host=None, verbose=False):
        self.account, self.password, self.version, self.verbose = account.encode(), password.encode(), version, verbose
        self.listserver, self.game_host = listserver, game_host
        self.levels, self.npcs, self.players, self.weapons = {}, {}, {}, {}
        self.me = {}; self.level_name = None; self.gmap = None; self.cur_loading = None; self.disc_message = ""
        self.chat = []; self.pm = []; self.pms = []; self.online = {}; self.map_positions = {}; self.map_asked = 0.0; self.pm_log = []; self.last_pm_sent = 0.0; self.server_text = []; self.log = []
        self.lp = LineParser(); self.conn = None; self.pos = (0, 0); self.frames = 0
        self.items = []; self.flag_values = {}; self.horses = []; self.chests = {}; self.flags = set(); self.tokens = []; self.arrays = {}; self.texts = {}; self.polys = {}; self.imgs = {}; self.sign = ("", 0.0); self.effect = None; self.defmovement = True; self.unsupported = {}; self.actions = []; self.vars = {}; self.account_name = account; self.ani_replace = {}; self.frozen_until = 0.0; self.gani_start = 0.0; self.weapon_ani_until = 0.0
        self.runner = WeaponRunner(self); self.npcrt = NpcRuntime(self); self.proj = Projectiles(self); self.bombs = Bombs(self); self.input = Input(self); self.gui = Gui(self); self.npcserver = NpcServer(self); self.timers = {}; self.map_cell = None; self.coll = collision.Collision(); self.attack_until = 0.0

    def set_nickname(self, nick):
        """Player prop 0 (NICKNAME): what the real client sends in its first props line; the server may add the guild tag."""
        nick = nick.strip()[:30]
        if nick: self.me["NICKNAME"] = nick; self.send(gline(2, gchar(0) + gstr(nick.encode("latin1", "replace"))))

    def set_appearance(self, head=None, body=None):
        """Wear another head and / or body: player props 11 (head: length + 100, then the name) and 35 (body), what `sethead` and `setbody` send."""
        out = b""
        if head: h = head.encode("latin1", "replace")[:100]; out += gchar(11) + gchar(len(h) + 100) + h; self.me["HEADIMAGE"] = head
        if body: out += gchar(35) + gstr(body.encode("latin1", "replace")[:200]); self.me["BODYIMAGE"] = body
        if out: self.send(gline(2, out))
        return bool(out)

    def connect(self, servers=None):
        if servers is None:
            from minclient import list_servers_full
            infos, _ = list_servers_full(*self.listserver, self.account, self.password, False)
            servers = [(i["host"], i["port"]) for i in infos]
            if infos and not getattr(self, "server_name", None): self.server_name = infos[0]["name"]
        host, port = servers[0]
        if self.game_host: host = self.game_host
        self.conn = Conn(host, port); v = VERSIONS[self.version]; self.v = v
        import config, filefetch, assets
        world = filefetch.world_folder_name(getattr(self, "server_name", None) or f"{host}_{port}".replace(":", "_"))
        self.files = filefetch.Fetcher(self, os.path.join(config.CFG["worlds_dir"], world)); assets.fetcher = self.files   # worlds/<server name>/
        self.conn.send(game_login(self.conn.seed, v["game"], self.account, self.password))
        self.conn.send(language() + gline(39, v["id39"]))
        now = time.time(); self.timers = dict(hb39=now + 3.2, hb24=now + 5.1)

    def close(self):
        import assets
        if assets.fetcher is getattr(self, "files", None): assets.fetcher = None
        self.conn.close()

    def send(self, line): self.conn.send(line)

    def heartbeat(self):
        now = time.time()
        if now >= self.timers["hb39"]: self.send(gline(39, self.v["id39"])); self.timers["hb39"] = now + 3.2
        if now >= self.timers["hb24"]: self.send(gline(24, gchar(9))); self.timers["hb24"] = now + 5.1

    def pump(self, secs=0.1):
        end = time.time() + secs
        while True:
            for t, plain in self.conn.frames(max(0.02, end - time.time())):
                self.frames += 1
                for item in self.lp.feed(plain): self.safe_handle(*item)
            self.heartbeat(); self.tick_all()
            if time.time() >= end: return

    def ensure_current_board(self):
        """The level we are in has no board (the server did not send it again, or it got lost): ask for it, at most every 2 s."""
        lv = self.levels.get(self.level_name) if self.level_name else None
        if not self.level_name or (lv is not None and lv.board): return
        now = time.time()
        if now - self.__dict__.get("_board_asked", 0.0) > 2.0: self._board_asked = now; self.request_level(self.level_name)

    def sync_cell_level(self):
        """On a gmap the level we are in is the one at our cell. When the server moves us in (PLAYERWARP2) before we have the map file (it is fetched on demand), the name could not be
        looked up: do it as soon as the rows are here, otherwise the old level stays 'current' and the new map is drawn as black."""
        if not self.gmap or not self.map_cell: return False
        rows = self.gmap_rows(); cx, cy = self.map_cell
        if not rows or not (0 <= cy < len(rows) and 0 <= cx < len(rows[0])): return False
        want = rows[cy][cx]
        if want and want != self.level_name:
            self.level_name = want; self.ensure_neighbours(); return True
        return False

    def _enter_world(self, new_key):
        """The server put us in another world (a gmap, or a plain level): the NPCs, items and horses of the old one must not be drawn in the new one (cell coordinates only mean something inside
        one map; the worldmap's NPC pictures showed up in portwolfe). They are put aside under the old world's name instead of dropped, because gs2emu does not send a level's NPCs again
        to a client that already had them: coming back, the NPCs - and with them the `addtiledef` lines of their scripts, i.e. the tiles - would be gone (black screen on the second visit)."""
        old = self.gmap or self.level_name
        if not new_key or new_key == old: return
        if getattr(self, "_loop_from_level", False) and getattr(self, "audio", None):   # the waves of portwolfe followed the player onto the worldmap
            self.audio.stop_loop(); self._loop_from_level = False
        self._remember_tiledefs(self.npcs)
        stash = self.__dict__.setdefault("_npc_stash", {})
        if old: stash[old] = self.npcs
        while len(stash) > 8: stash.pop(next(iter(stash)))
        self.npcs = stash.pop(new_key, {}); self.items = []; self.horses = []; self.npc_rev = getattr(self, "npc_rev", 0) + 1
        self.__dict__.pop("_adj_memo", None)
        try: import render; render._world_cache.clear(); render._fx_cache.clear()
        except Exception: pass

    _PREFIX_TILEDEF = re.compile(r"\baddtiledef2?\s+[^,;{}\n]+,\s*(?!\s|#L)[^,;{}\n]+,[^;{}\n]*")

    def _remember_tiledefs(self, npcs):
        """Keep the `addtiledef` lines with a level-name prefix (not #L) of the world we leave: in Graal they stay registered when you walk on. portwolfe_a1 registers
        `addtiledef2 ...,portwolfe_,...` for every portwolfe_ level, and portwolfe_alley2 has no tiledefs of its own: without this it was drawn with the plain tileset.
        removetiledefs lines are not kept, so a level that clears its own tiles cannot wipe out the TileDefs weapon in other levels."""
        mem = self.__dict__.setdefault("tiledef_memory", {})
        for n in npcs.values():
            lines = self._PREFIX_TILEDEF.findall(n.get("SCRIPT") or "")
            if lines: mem.setdefault(";\n".join(lines) + ";", None)
        while len(mem) > 300: mem.pop(next(iter(mem)))

    def safe_handle(self, kind, pid, payload):
        """`handle`, but a packet we cannot digest (a prop we do not know, a bug) is logged instead of ending the session."""
        try: self.handle(kind, pid, payload)
        except (ConnectionError, OSError): raise
        except Exception as e:
            self.log.append(f"packet {kind} {pid}: {type(e).__name__}: {e}")
            if len(self.log) < 400:
                try: import crashguard; crashguard.note(f"packet {kind} {pid} ({len(payload)} bytes) {bytes(payload[:2048])!r}")
                except Exception: pass

    def handle(self, kind, pid, payload):
        if kind == "raw":
            if pid == 101 and self.cur_loading and len(payload) == 8192:
                self.cur_loading.board = payload
                if not self.gmap and self.cur_loading.name == self.level_name: self.ensure_neighbours()
            elif pid == 102 and getattr(self, "files", None): self.files.on_file(payload)
            return
        name = enums.PLO.get(pid, f"?{pid}")
        if self.verbose: print(f"  {name} {payload[:60]!r}")
        if pid == 6:
            n = payload.decode("latin1")
            if n.endswith(".gmap"): self._enter_world(n); self.gmap = n
            else:
                self.cur_loading = self.levels.setdefault(n, Level(n)); self.cur_loading.links = []
                if self.level_name is None: self.level_name = n
        elif pid in (30, 45, 68, 69) and getattr(self, "files", None):
            {30: self.files.on_failed, 45: self.files.on_uptodate, 68: self.files.on_large_start, 69: self.files.on_large_end}[pid](payload.decode("latin1"))
        elif pid == 16: self.disc_message = payload.decode("latin1", "replace").strip()
        elif pid == 1 and self.cur_loading: self.cur_loading.links.append(payload.decode("latin1").split())
        elif pid == 5 and self.cur_loading and len(payload) >= 2:
            from messagebox import decode_sign; self.cur_loading.signs.append((payload[0] - 0x20, payload[1] - 0x20, decode_sign(payload[2:])))
        elif pid == 9:
            props = parse_player(payload); self.me.update(props); self._own_pos(props)
        elif pid == 8:
            pidn = gint(payload[:2]); newp = parse_player(payload[2:])
            if "DISCONNECT" in newp: self.online.pop(pidn, None)
            else:
                o = self.online.setdefault(pidn, {}); o.update({k: v for k, v in newp.items() if k in ("NICKNAME", "ACCOUNTNAME", "LEVEL", "COMMUNITYNAME", "X2", "Y2", "GMAPLEVELX", "GMAPLEVELY")})
            if newp.get("JOINLEAVELVL") == 0: self.players.pop(pidn, None); newp = {}
            elif newp: d = self.players.setdefault(pidn, {}); d.update(newp)
            d = self.players.get(pidn, {})
            if "MESSAGE" in d and d["MESSAGE"]: self.chat.append((pidn, d.get("NICKNAME", f"#{pidn}"), d["MESSAGE"]))
        elif pid == 3:
            try: nid, props = parse_npc(payload)
            except ValueError as e:   # an unknown prop, or the packet ends inside one: keep what was read before it, and log the whole packet
                if getattr(e, "partial", None) and hasattr(e, "npc_id"):
                    self.npcs.setdefault(e.npc_id, {}).update(e.partial)
                    if "SCRIPT" in e.partial: self.npc_rev = getattr(self, "npc_rev", 0) + 1
                self.log.append(f"npc parse: {e}")
                if len(self.log) < 400:
                    try: import crashguard; crashguard.note(f"npc props {e} ({len(payload)} bytes) {bytes(payload[:2048])!r}")
                    except Exception: pass
            else:
                if nid not in self.npcs: self.npc_rev = getattr(self, "npc_rev", 0) + 1
                self.npcs.setdefault(nid, {}).update(props)
                if "SCRIPT" in props: self.npc_rev = getattr(self, "npc_rev", 0) + 1   # render's world cache key (instead of summing all scripts every frame)
        elif pid == 33:
            try:
                r = Reader(payload); name = r.gstr(); r.byte(); image = r.gstr(); r.byte(); script = r.raw(r.num(2)).replace(b"\xa7", b"\n").decode("latin1")
                self.weapons[name] = payload; self.runner.add(name, image, script)
            except Exception as e: self.log.append(f"weapon parse: {e}")
        elif pid == 34: n = payload.decode("latin1"); self.weapons.pop(n, None); self.runner.weapons.pop(n, None)
        elif pid == 194: self.weapons.clear(); self.runner.weapons.clear()
        elif pid == 19 and len(payload) >= 7:
            ax_, ay_, fl = (payload[2] - 0x20) / 2, (payload[3] - 0x20) / 2, payload[4] - 0x20
            self.proj.remote_arrow(ax_, ay_, fl & 3, bool(fl & 8))
        elif pid == 41: self.start_message = payload.decode("latin1")
        elif pid == 21: pass
        elif pid == 154: self.server_frozen = True
        elif pid == 155: self.server_frozen = False
        elif pid == 10: self.is_leader = True
        elif pid == 46 and len(payload) >= 5:
            hx, hy = ((payload[3] - 0x20) / 2) * 16, ((payload[4] - 0x20) / 2) * 16; cx_, cy_ = self.cell if self.gmap else (0, 0); hx += cx_ * 1024; hy += cy_ * 1024
            self.hit_npcs("washit", lambda q: q[0] <= hx < q[0] + q[2] and q[1] <= hy < q[1] + q[3])
        elif pid == 29 and len(payload) >= 3: self.npcs.pop(gint(payload[:3]), None); self.npc_rev = getattr(self, "npc_rev", 0) + 1
        elif pid == 150 and len(payload) >= 4:
            ln = payload[0] - 0x20
            if len(payload) >= 1 + ln + 3 and payload[1:1 + ln].decode("latin1") == self.level_name: self.npcs.pop(gint(payload[1 + ln:4 + ln]), None); self.npc_rev = getattr(self, "npc_rev", 0) + 1
        elif pid == 40 and len(payload) >= 5: self.hurt_by_server((payload[2] - 0x20) - 64, (payload[3] - 0x20) - 64, payload[4] - 0x20)
        elif pid == 11 and len(payload) >= 5:
            self.bombs.put((payload[2] - 0x20) / 2, (payload[3] - 0x20) / 2, payload[4] - 0x20, send=False, remote=True)
        elif pid == 12 and len(payload) >= 2: self.bombs.remove((payload[0] - 0x20) / 2, (payload[1] - 0x20) / 2)
        elif pid == 36 and len(payload) >= 6:
            cx_, cy_ = self.cell if self.gmap else (0, 0); self.blast_hits(cx_ * 1024 + (payload[3] - 0x20) * 8, cy_ * 1024 + (payload[4] - 0x20) * 8, payload[2] - 0x20)
        elif pid == 17 and len(payload) >= 4:
            hx, hy, hdir = (payload[0] - 0x20) / 2, (payload[1] - 0x20) / 2, (payload[2] - 0x20) & 3; img = payload[3:].decode("latin1")
            if img and not any(abs(h[1] - hx) < 0.3 and abs(h[2] - hy) < 0.3 for h in self.horses): self.horses.append((img, hx, hy, self.cell if self.gmap else (0, 0), hdir))
        elif pid == 18 and len(payload) >= 2:
            hx, hy = (payload[0] - 0x20) / 2, (payload[1] - 0x20) / 2; self.horses[:] = [h for h in self.horses if not (abs(h[1] - hx) < 0.6 and abs(h[2] - hy) < 0.6)]
        elif pid == 28 and payload:
            txt_ = payload.decode("latin1"); name_, _, val_ = txt_.partition("=")
            self.flags.add(name_); self.flag_values[name_] = val_
        elif pid == 31 and payload: n_ = payload.decode("latin1").split("=")[0]; self.flags.discard(n_); self.flag_values.pop(n_, None)
        elif pid == 7 and len(payload) >= 4 and payload[0] - 0x20 < 64:
            self._apply_board(self.levels.get(self.level_name), payload)
        elif pid == 186 and len(payload) >= 6:
            rows = self.gmap_rows(); mx, my = payload[0] - 0x20, payload[1] - 0x20
            if rows and 0 <= my < len(rows) and 0 <= mx < len(rows[0]): self._apply_board(self.levels.get(rows[my][mx]), payload[2:])
        elif pid == 4 and len(payload) >= 3:
            ch = dict(opened=bool(payload[0] - 0x20), x=payload[1] - 0x20, y=payload[2] - 0x20, item=(payload[3] - 0x20) if len(payload) > 3 and not payload[0] - 0x20 else None)
            lst = self.chests.setdefault(self.level_name, []); lst[:] = [c for c in lst if (c["x"], c["y"]) != (ch["x"], ch["y"])] + [ch]
        elif pid == 22 and len(payload) >= 3:
            self.items.append(dict(x=(payload[0] - 0x20) * 8, y=(payload[1] - 0x20) * 8, type=payload[2] - 0x20,
                                   cell=self.cell, level=self.level_name, t0=time.time()))
        elif pid == 23 and len(payload) >= 2:
            x, y = (payload[0] - 0x20) * 8, (payload[1] - 0x20) * 8
            self.items = [i for i in self.items if not (i["x"] == x and i["y"] == y and i["level"] == self.level_name)]
        elif pid == 48 and len(payload) >= 7:
            fromp, npc, x, y = gint(payload[:2]), gint(payload[2:5]), (payload[5] - 0x20) / 2, (payload[6] - 0x20) / 2
            items = csv_split(payload[7:].decode("latin1")); self.actions.append((fromp, npc, x, y, items))
            if len(items) >= 3 and items[0].lower() == "clientside" and items[1].lower() == "-guilds": self._guild_reply(items[2:])   # the server's gr.guild answers
            elif len(items) >= 3 and items[0].lower() == "clientside":
                self.runner.broadcast("action" + items[2].lower(), params=items[3:], only=items[1])
            elif items: self.runner.broadcast("action" + items[0].lower(), params=items[1:])
        elif pid == 37 and self._map_players_reply(payload): pass
        elif pid == 37:
            self.pm.append(payload.decode("latin1"))
            try: parts = [x for x in csv_split(payload[2:].decode("latin1")) if x]; self.pms.append(dict(sender=gint(payload[:2]), title=parts[0] if len(parts) > 1 else "", text=parts[-1] if parts else ""))
            except Exception: pass
            self._log_pm(payload)
        elif pid == 165: self.npc_move_packet(payload)
        elif pid == 189: self.npc_move_packet(payload, v2=True)
        elif pid == 175: self.proj.remote(payload)
        elif pid == 13: self.chat.append((None, "toall", payload.decode("latin1")))
        elif pid == 82: self.server_text.append(payload.decode("latin1"))
        elif pid == 49 and len(payload) >= 5:
            self.pos = ((payload[0] - 0x20) * 8, (payload[1] - 0x20) * 8)
            self.map_cell = (payload[3] - 0x20, payload[4] - 0x20)
            if len(payload) > 5: g_ = payload[5:].decode("latin1"); self._enter_world(g_); self.gmap = g_
            rows = self.gmap_rows(); cx, cy = self.map_cell
            if rows and 0 <= cy < len(rows) and 0 <= cx < len(rows[0]): self.level_name = rows[cy][cx]
        elif pid == 14 and len(payload) >= 2:
            new_level = payload[2:].decode("latin1"); self._enter_world(new_level)
            self.pos = ((payload[0] - 0x20) * 8, (payload[1] - 0x20) * 8); self.level_name = new_level; self.gmap = None
            self.map_cell = None
        elif pid == 15: self.log.append("warp failed")

    def _own_pos(self, props):
        """Our position from a PLAYERPROPS packet, only when it carries one (X2/Y2 in pixels, or X/Y in half tiles); other props leave it alone."""
        x, y = self.pos
        if "X2" in props or "Y2" in props: self.pos = (props.get("X2", x), props.get("Y2", y))
        elif "X" in props or "Y" in props: self.pos = (props["X"] * 8 if "X" in props else x, props["Y"] * 8 if "Y" in props else y)

    def request_level(self, name, modtime=0):
        self.send(gline(35, gint_enc(modtime, 5) + name.encode()))

    def say(self, text):
        self.send(gline(2, gchar(12) + gstr(text.encode("latin1")[:223])))
        self.me["MESSAGE"] = text; self.say_time = time.time()
        self.chat.append((None, "me", text))
    def online_players(self):
        """The other players on the server, sorted by nickname: [{id, nick, account, level}]."""
        out = [dict(id=i, nick=str(o.get("NICKNAME") or ""), account=str(o.get("ACCOUNTNAME") or ""), level=str(o.get("LEVEL") or "")) for i, o in self.online.items() if o.get("ACCOUNTNAME") and not str(o["ACCOUNTNAME"]).startswith("(")]
        return sorted(out, key=lambda p: (p["nick"] or p["account"]).lower())

    def player_name(self, pid):
        o = self.online.get(pid) or {}
        return str(o.get("NICKNAME") or o.get("ACCOUNTNAME") or f"#{pid}")

    def send_pm(self, ids, text, limit=True):
        """PLI_PRIVATEMESSAGE: {GSHORT count}{GSHORT id...}{message}. The server allows one message every 4 seconds. Returns (ok, reason)."""
        if isinstance(ids, int): ids = [ids]
        text = text.strip()
        if not text or not ids: return False, "nothing to send"
        wait = 4.0 - (time.time() - self.last_pm_sent) if limit else 0
        if wait > 0: return False, "wait %d s before the next message" % (int(wait) + 1)
        self.send(gline(28, gint_enc(len(ids), 2) + b"".join(gint_enc(i, 2) for i in ids) + csv_join([text]).encode("latin1", "replace")))
        self.last_pm_sent = time.time()
        self.pm_log.append(dict(t=time.time(), dir="out", who=", ".join(self.player_name(i) for i in ids), text=text)); del self.pm_log[:-200]
        return True, ""

    MAP_PLAYERS_MARK = "MAPPLAYERS"
    MAP_PLAYERS_EVERY = 3.0

    def request_map_players(self):
        """Ask the server's MapPlayers-NPC (server/npcMapPlayers.txt) where every player is: it answers with one private message
        `MAPPLAYERS` + account,level,x,y for each player, x and y in tiles of the whole gmap. gs2emu does not send the moves of far away players itself."""
        now = time.time()
        if now - self.map_asked < self.MAP_PLAYERS_EVERY or getattr(self, "local_inventory", False): return False
        self.map_asked = now; self.send_triggeraction(0, 0, 0, ["servermapplayers"]); return True

    def _map_players_reply(self, payload):
        """The answer to request_map_players (never shown as a private message). Returns True if the packet was one."""
        try: parts = [x for x in csv_split(payload[2:].decode("latin1")) if x]
        except Exception: return False
        if not parts or not parts[-1].startswith(self.MAP_PLAYERS_MARK): return False
        items = parts[-1][len(self.MAP_PLAYERS_MARK):].split(","); now = time.time()
        for i in range(0, len(items) - 3, 4):
            try: self.map_positions[items[i]] = (items[i + 1], float(items[i + 2]) * 16, float(items[i + 3]) * 16, now)
            except ValueError: continue
        return True

    def _log_pm(self, payload):
        try:
            sender = gint(payload[:2]); parts = [x for x in csv_split(payload[2:].decode("latin1")) if x]
            if parts: self.pm_log.append(dict(t=time.time(), dir="in", who=self.player_name(sender), text=" ".join(parts[1:] if len(parts) > 1 else parts))); del self.pm_log[:-200]
        except Exception: pass

    def clear_chat(self):
        self.send(gline(2, gchar(12) + gstr(b""))); self.me["MESSAGE"] = ""
    def walk(self, direction, steps, delay=0.05, stop_on_link=True):
        """Scripted walking (same per-tick logic as the interactive client: walls, links, gmap edges, weapon-owned ganis)."""
        taken = None
        for k in range(steps):
            link = self.step(direction, k == 0)
            self.pump(delay)
            if link and stop_on_link: taken = link; break
        self.stop(); self.pump(0.2)
        if taken: self.pump(1.2)
        return taken

    def warp(self, level, x_px, y_px):
        self.pos = (int(x_px) // 8 * 8, int(y_px) // 8 * 8)
        if level != self.level_name: self.level_name = None
        if level != self.level_name and not (self.gmap and level in {n for r in (self.gmap_rows() or []) for n in r}):
            self.gmap = None; self.map_cell = None
        self.send(gline(0, gchar(int(x_px) // 8) + gchar(int(y_px) // 8) + level.encode()))


    def tick_all(self):
        """Everything that advances with time: weapon / NPC / GUI scripts, projectiles, bombs, the local NPC server, server-commanded walking."""
        self.sync_cell_level(); self.ensure_current_board(); self.runner.tick(); self.npcrt.tick(); self.proj.tick(); self.bombs.tick(); self.gui.tick(); self.npcserver.tick(); self.npc_moves_tick(); getattr(self, "files", None) and self.files.tick(); self._track_update(); self._keys_tick(); self._carry_tick(); self.death_tick(); self._mission_tick(); self._walk_tick(); self.update_gani()

    def _gpos(self): cx, cy = self.cell if self.gmap else (0, 0); return (cx * 1024 + self.pos[0], cy * 1024 + self.pos[1])

    def _blocked_g(self, gx, gy):
        cx, cy = self.cell if self.gmap else (0, 0); return self.coll.blocked(self, gx - cx * 1024, gy - cy * 1024)

    def free_spot(self, x_tiles, y_tiles, cell=None, radius=48):
        """Position (level-local px in `cell`) nearest to the wanted tile position where the player's box is free; None if there is none.
        Levels that are not loaded count as free (their tile data is unknown)."""
        cx, cy = self.cell if self.gmap else (0, 0); tcx, tcy = cell if cell is not None else (cx, cy)
        g = (tcx * 1024 + int(round(x_tiles * 2)) * 8, tcy * 1024 + int(round(y_tiles * 2)) * 8); p = pathing.nearest_free(self._blocked_g, g, radius)
        return None if p is None else (p[0] - tcx * 1024, p[1] - tcy * 1024)

    AVOID_NEAR = 24
    AVOID_HARD = 16
    AVOID_COST = 64

    walk_task = None; mission = None; walk_result = ""
    clock = staticmethod(time.time)
    TRACK_WINDOW = 0.7
    MAX_SPEED = 200.0

    def _others_keyed(self):
        """[(key, global px)] of the other players this client knows: players the game server shows us, plus the other local clients of a shared NPC server."""
        out = []; me = getattr(self, "account_name", "").lower(); cx, cy = self.cell if self.gmap else (0, 0)
        for pid, p in list(self.players.items()):
            acc = str(p.get("ACCOUNTNAME", "")).lower()
            if "X2" not in p or acc == me or acc == "(npcserver)": continue
            pc = (p.get("GMAPLEVELX", cx), p.get("GMAPLEVELY", cy)) if self.gmap else (0, 0)
            out.append((acc or ("id", pid), (pc[0] * 1024 + p["X2"], pc[1] * 1024 + p["Y2"])))
        known = {k for k, _ in out}
        for o in list(self.npcserver.sessions.values()):
            if o is self or o.level_name is None: continue
            if (o.gmap or None) != (self.gmap or None) or (not self.gmap and o.level_name != self.level_name): continue
            k = getattr(o, "account_name", "").lower()
            if k not in known: out.append((k, o._gpos()))
        return out

    def others_global(self): return [g for _, g in self._others_keyed()]

    def _track_update(self, now=None):
        """Remember when each other player's position changed: the history the velocity estimate (prediction) comes from."""
        import collections
        now = now or self.clock(); tr = self.__dict__.setdefault("_tracks", {}); cur = dict(self._others_keyed())
        for k, g in cur.items():
            dq = tr.setdefault(k, collections.deque(maxlen=32))
            if not dq or dq[-1][1] != g: dq.append((now, g))
        for k in [k for k in tr if k not in cur]: del tr[k]

    use_peer_routes = True
    turn_aware = True

    WALK_SPEED = 160.0

    @staticmethod
    def _heading(samples, n):
        """Unit direction of the net displacement over the last `n` position changes (positions only: arrival times from the network are jittery), or None."""
        pts = [samples[0][1]] + [s[1] for i, s in enumerate(samples[1:], 1) if s[1] != samples[i - 1][1]]
        if len(pts) < 2: return None
        a, b = pts[max(0, len(pts) - 1 - n)], pts[-1]; dx, dy = b[0] - a[0], b[1] - a[1]; d = (dx * dx + dy * dy) ** 0.5
        return None if d < 8 else (dx / d, dy / d)

    def _estimate(self, dq, now):
        """(vx, vy) of one player: walking speed along the heading of its recent position changes. Longer-term heading over the last ~0.7 s of
        history, the latest 2 changes for turns: when they disagree the player has just turned and the latest wins. A player with no
        position change for 0.4 s is stopped."""
        t1 = dq[-1][0]
        recent = [s for s in dq if now - s[0] <= self.TRACK_WINDOW]
        if len(recent) < 2 or now - t1 > 0.4: return (0.0, 0.0)
        longer = self._heading(recent, 12)
        if not self.turn_aware: h = longer
        else:
            latest = self._heading(recent, 2); h = longer if latest is None else latest if longer is None else (latest if longer[0] * latest[0] + longer[1] * latest[1] < 0.9 else longer)
        return (h[0] * self.WALK_SPEED, h[1] * self.WALK_SPEED) if h else (0.0, 0.0)

    def _extrapolate(self, p0, v, horizon, branch=True):
        """Positions at 0, 50, 100, ... ms. Constant velocity; at a wall the main path stops and (with `branch`) two more paths slide along
        the wall to either side at the same speed, since a player that is walking somewhere usually turns instead of stopping."""
        px, py = p0; paths = []; main = [(px, py)]; hit = None
        for i in range(1, horizon + 1):
            nx, ny = px + v[0] * 0.05, py + v[1] * 0.05
            if self._blocked_g(int(nx) // 8 * 8, int(ny) // 8 * 8):
                hit = (px, py, i); break
            px, py = nx, ny; main.append((px, py))
        if hit: main.extend([(hit[0], hit[1])] * (horizon + 1 - len(main)))
        paths.append(main)
        if hit and branch:
            sp = (v[0] ** 2 + v[1] ** 2) ** 0.5
            for sv in ((-v[1], v[0]), (v[1], -v[0])):
                n = (sv[0] ** 2 + sv[1] ** 2) ** 0.5 or 1.0; sv = (sv[0] / n * sp, sv[1] / n * sp); qx, qy = hit[0], hit[1]; alt = main[:hit[2]]
                for i in range(hit[2], horizon + 1):
                    nx, ny = qx + sv[0] * 0.05, qy + sv[1] * 0.05
                    if not self._blocked_g(int(nx) // 8 * 8, int(ny) // 8 * 8): qx, qy = nx, ny
                    alt.append((qx, qy))
                paths.append(alt)
        return paths

    def predicted_others(self, now=None, horizon=40):
        """Predicted positions of every other player, one list per hypothesis, index k = k * 50 ms from now:
        - a player of a local client that is walking: its real remaining path (turns included);
        - otherwise constant velocity estimated from the position history (following turns), with wall-sliding alternatives where it would hit a wall;
        - a player that has not moved for 0.4 s: predicted to stay."""
        now = now or self.clock(); out = []
        for k, dq in list(self.__dict__.get("_tracks", {}).items()):
            peer = self.npcserver.sessions.get(k) if isinstance(k, str) and self.use_peer_routes else None
            if peer is not None and peer is not self and peer.walking_to():
                nodes = [peer._gpos()] + list(peer.walk_task["path"]); nodes = nodes[:horizon + 1]; nodes += [nodes[-1]] * (horizon + 1 - len(nodes)); out.append(nodes); continue
            t1, g1 = dq[-1]; v = self._estimate(dq, now)
            lead = min(max(0.0, now - t1), 0.4) if (v[0] or v[1]) else 0.0
            out.extend(self._extrapolate((g1[0] + v[0] * lead, g1[1] + v[1] * lead), v, horizon, branch=bool(v[0] or v[1])))
        return out

    def _avoid_tcost(self, paths):
        """Price of standing at (x, y) after k steps: near where another player stands now (as in the static avoidance, so prediction never
        makes the walker less careful) or near where it is predicted to be at step k (+-2 steps of slack)."""
        near, cost = self.AVOID_NEAR, self.AVOID_COST
        if not paths: return None
        now_pos = [p[0] for p in paths]
        def f(x, y, k):
            if any(abs(x - ox) < near and abs(y - oy) < near for ox, oy in now_pos): return cost
            for path in paths:
                for i in range(max(0, min(k, len(path) - 1) - 2), min(len(path) - 1, k + 2) + 1):
                    if abs(x - path[i][0]) < near and abs(y - path[i][1]) < near: return cost
            return 0
        return f

    def _avoid_costs(self, others):
        """(static cost, time-aware cost) for the A*: with `predict_players` (default) the other players are priced where they will be when we get
        there, otherwise where they stand now."""
        if not others: return None, None
        if getattr(self, "predict_players", True):
            self._track_update(); t = self._avoid_tcost(self.predicted_others())
            if t: return None, t
        return self._avoid_cost(others), None

    def _avoid_cost(self, others):
        near, cost = self.AVOID_NEAR, self.AVOID_COST
        return (lambda x, y: cost if any(abs(x - ox) < near and abs(y - oy) < near for ox, oy in others) else 0) if others else None

    predict_npcs = True

    def npc_move_packet(self, payload, v2=False):
        self._motion_cache = None
        """PLO_MOVE {GINT3 npc}{x/8}{y/8}{dx/8+100}{dy/8+100}{GSHORT 50 ms ticks}{options}, repeated for a queue of moves, or PLO_MOVE2 (v2): the same
        with pixel coordinates {px x}{px y}{px dx}{px dy} (2 bytes each, value*2 | sign, as the X2/Y2 props) which newer clients get. The NPC
        then glides from each start position by (dx, dy) in the given time (level-local px); `npc_moves_tick` applies it every frame."""
        import props
        try:
            r = Reader(payload); nid = r.num(3); segs = []; t = self.clock()
            while r.left() >= (11 if v2 else 7):
                if v2: x, y, dx, dy = props._px(r), props._px(r), props._px(r), props._px(r)
                else: x, y = r.byte() * 8, r.byte() * 8; dx, dy = (r.byte() - 100) * 8, (r.byte() - 100) * 8
                dur = max(r.num(2) * 0.05, 0.05); r.byte()
                segs.append((t, t + dur, (x, y), (x + dx, y + dy))); t += dur
        except (IndexError, ValueError): return
        n = self.npcs.get(nid)
        if n is not None and segs: n["_moves"] = segs

    def _move_pos(self, segs, t):
        """Level-local px position at time t along a move queue (before the first move: its start; after the last: its end)."""
        for a, b, p, q in segs:
            if t < a: return p
            if t <= b: f = (t - a) / (b - a); return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f)
        return segs[-1][3]

    def npc_moves_tick(self, now=None):
        now = now or self.clock()
        for nid, n in list(self.npcs.items()):
            segs = n.get("_moves")
            if not segs: continue
            x, y = self._move_pos(segs, now); n["X2"], n["Y2"] = int(x), int(y)
            if now >= segs[-1][1]: del n["_moves"]

    def npc_motion(self, now=None, horizon=40):
        """{npc id: [global px of the NPC at step k]} for every NPC that is moving: a script tween (`move`) or a move queue from the server."""
        now = now or self.clock(); key = (int(now * 20), horizon, len(self.npcs), self.npcrt.version, self.gmap)
        c = self.__dict__.get("_motion_cache")
        if c and c[0] == key: return c[1]
        out = {}
        for nid, n in self.npcs.items():
            cx, cy = (n.get("GMAPLEVELX", 0), n.get("GMAPLEVELY", 0)) if self.gmap else (0, 0)
            inst = self.npcrt.inst.get(nid)
            if n.get("_moves"):
                out[nid] = [(cx * 1024 + p[0], cy * 1024 + p[1]) for p in (self._move_pos(n["_moves"], now + k * 0.05) for k in range(horizon + 1))]
            elif inst is not None and (inst.tween or (getattr(self, "npc_lookahead", True) and self.npcrt.can_move(inst))):
                path = self.npcrt.lookahead(nid, now, horizon) if getattr(self, "npc_lookahead", True) else None
                if path is not None:
                    if any(abs(p[0] - path[0][0]) > 0.5 or abs(p[1] - path[0][1]) > 0.5 for p in path): out[nid] = path
                elif inst.tween:
                    t0, dur, x0, y0, x1, y1 = inst.tween
                    out[nid] = [(cx * 1024 + (x0 + (x1 - x0) * min(1.0, max(0.0, (now + k * 0.05 - t0) / dur))) * 16, cy * 1024 + (y0 + (y1 - y0) * min(1.0, max(0.0, (now + k * 0.05 - t0) / dur))) * 16) for k in range(horizon + 1)]
        self._motion_cache = (key, out)
        return out

    def _blocked_plan(self, gx, gy):
        """Collision for path planning: walls and *standing* NPC shapes; NPCs that are moving are priced by `_npc_tcost` instead."""
        cx, cy = self.cell if self.gmap else (0, 0)
        return self.coll.blocked(self, gx - cx * 1024, gy - cy * 1024, skip=self._moving_ids() if getattr(self, "predict_npcs", True) else None)

    def _moving_ids(self):
        """Ids of the NPCs that are moving now or will within the look-ahead horizon (their shape is priced where it will be instead of being a hard
        obstacle), doors and gates that can be opened (touch, chat line, flag, key, item, grab), and NPCs the player can push. Cached per clock reading:
        the planner asks for every node it expands."""
        stamp = (round(self.clock() * 50), len(self.npcrt.inst), len(self.npcs)); c = self.__dict__.get("_mv_cache")
        if c and c[0] == stamp: return c[1]
        ids = set(self.npc_motion(horizon=40))
        if getattr(self, "npc_openers", True):
            dc = getattr(self, "door_commands", True); ids |= set(self.npcrt.doors(self.clock(), chat=dc, flags=dc))
        if self.push_npcs: ids |= self._pushable_ids()
        self._mv_cache = (stamp, ids); return ids

    def _pushy(self, i):
        """The engine's `canbepushed`, or - offline only - the canpush-canpull class that answers `actionpushed`. Online the server owns such NPCs (our local
        move would be undone by its NPC props), and counting them as passable made the live crossing walk bump into crates (simulate_two: 8 px)."""
        return i.fx.pushable or (getattr(self, "local_inventory", False) and "actionpushed" in i.alllow)

    def _pushable_ids(self): return {nid for nid, i in self.npcrt.inst.items() if self._pushy(i) and i.fx.shape and not i.fx.noblock}

    NPC_COST = 160

    def _npc_tcost(self):
        """f(x, y, k): price of standing at (x, y) after k steps when the walker's box would overlap a moving NPC's shape there (+-2 steps of slack)."""
        if not getattr(self, "predict_npcs", True): return None
        motion = self.npc_motion()
        if not motion: return None
        me = self._gpos(); shapes = []
        for nid, path in motion.items():
            if abs(path[0][0] - me[0]) > 2400 or abs(path[0][1] - me[1]) > 2400: continue
            rects = self.coll.npc_rects_of(self, nid)
            if not rects: continue
            offs = [(p[0] - path[0][0], p[1] - path[0][1]) for p in path]
            sx0 = min(r[0] for r in rects) + min(o[0] for o in offs) - 4; sy0 = min(r[1] for r in rects) + min(o[1] for o in offs) - 4
            sx1 = max(r[0] + r[2] for r in rects) + max(o[0] for o in offs) + 4; sy1 = max(r[1] + r[3] for r in rects) + max(o[1] for o in offs) + 4
            shapes.append((rects, offs, (sx0, sy0, sx1, sy1)))
        if not shapes: return None
        bx, by, bw, bh = 16, 32, 16, 16; cost = self.NPC_COST
        def f(x, y, k):
            x0, y0 = x + bx, y + by
            for rects, offs, (sx0, sy0, sx1, sy1) in shapes:
                if x0 >= sx1 or x0 + bw <= sx0 or y0 >= sy1 or y0 + bh <= sy0: continue
                for i in range(max(0, min(k, len(offs) - 1) - 2), min(len(offs) - 1, k + 2) + 1):
                    dx, dy = offs[i]
                    for rx, ry, rw, rh in rects:
                        if x0 < rx + dx + rw + 4 and x0 + bw > rx + dx - 4 and y0 < ry + dy + rh + 4 and y0 + bh > ry + dy - 4: return cost
            return 0
        return f

    PUSH_COST = 60
    PUSH_COST_CLASS = 400
    DOOR_COST_TOUCH = 40
    DOOR_COST_COMMAND = 600

    def _door_cost(self):
        """f(x, y): price of walking through a door's shape. A door that opens on touch costs a little, one that needs a chat line or a flag costs a
        lot, so the walker goes around when a detour exists and says a line only when it has to."""
        dc = getattr(self, "door_commands", True); doors = self.npcrt.doors(self.clock(), chat=dc, flags=dc) if getattr(self, "npc_openers", True) else {}
        shapes = [(self.coll.npc_rects_of(self, nid), self.DOOR_COST_TOUCH if w["how"] == "touch" and not (w.get("flags") or w.get("keys") or w.get("items")) else self.DOOR_COST_COMMAND) for nid, w in doors.items()]
        if self.push_npcs: shapes += [(self.coll.npc_rects_of(self, nid), self.PUSH_COST if self.npcrt.inst[nid].fx.pushable else self.PUSH_COST_CLASS) for nid in self._pushable_ids() if nid not in doors]
        shapes = [(r, c) for r, c in shapes if r]
        if not shapes: return None
        boxed = [(min(q[0] for q in r), min(q[1] for q in r), max(q[0] + q[2] for q in r), max(q[1] + q[3] for q in r), r, c) for r, c in shapes]
        def f(x, y):
            x0, y0 = x + 16, y + 32; worst = 0; x1, y1 = x0 + 16, y0 + 16
            for bx0, by0, bx1, by1, rects, c in boxed:
                if c > worst and x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0 and any(x0 < rx + rw and x1 > rx and y0 < ry + rh and y1 > ry for rx, ry, rw, rh in rects): worst = c
            return worst
        return f

    def _dynamic_costs(self, others):
        """Players and moving NPCs only (no doors / pushables): what can change while walking, and so what makes a replan worthwhile."""
        cost, tcost = self._avoid_costs(others); nt = self._npc_tcost()
        if nt is not None:
            if tcost is not None: tcost = (lambda x, y, k, _b=tcost: _b(x, y, k) + nt(x, y, k))
            elif cost is not None: tcost = (lambda x, y, k, _c=cost: _c(x, y) + nt(x, y, k)); cost = None
            else: tcost = nt
        return cost, tcost

    def _plan_costs(self, others):
        """(static cost, time-aware cost) for the A*: players (steps 22-24), moving NPCs (25-27) and doors / pushable NPCs combined."""
        cost, tcost = self._dynamic_costs(others); dcost = self._door_cost()
        if dcost is not None:
            c0 = cost; cost = (lambda x, y, _c=c0: dcost(x, y) + (_c(x, y) if _c else 0))
        return cost, tcost

    def walk_to(self, x_tiles, y_tiles, cell=None, _final=False):
        """Walk (8 px every 50 ms, walls / NPC shapes respected, no level links) to a level-local tile position, optionally in another gmap cell.
        The goal is moved to the nearest free spot within 3 tiles. Returns True when a path exists; `on_walk_done(result)` fires at the end
        with "arrived" or "blocked". Doors on the way that need a chat line or a flag: the chat line is said when the walker is at the door,
        flags are obtained first from an NPC that sets them (a chat line, or touching it), then the walk goes on (`door_commands`)."""
        cx, cy = self.cell if self.gmap else (0, 0); tcx, tcy = cell if cell is not None else (cx, cy)
        sx, sy = self._gpos()
        goal = (sx + round((tcx * 1024 + x_tiles * 16 - sx) / 8) * 8, sy + round((tcy * 1024 + y_tiles * 16 - sy) / 8) * 8)
        self._focus = (sx, sy, goal[0], goal[1])
        others = self.others_global() if getattr(self, "avoid_players", True) else []
        hard = self.AVOID_HARD; occupied = lambda x, y: self._blocked_plan(x, y) or any(abs(x - ox) < hard and abs(y - oy) < hard for ox, oy in others)
        free = pathing.nearest_free(occupied, goal)
        cost, tcost = self._plan_costs(others)
        path = pathing.find_path(self._blocked_plan, (sx, sy), free, cost=cost, tcost=tcost) if free else None
        if path is None: self.cancel_walk("blocked"); return False
        import collections
        steps = [] if _final or not getattr(self, "door_commands", True) else self._door_prelude(path)
        if steps:
            self.mission = dict(steps=collections.deque(steps), final=(x_tiles, y_tiles, cell), until=0.0, sub=None, await_flag=None)
            self.walk_stats = dict(path=collections.deque(), goal=free, replans=0, tick=0, wait=0, npcwait=0, npcwait_total=0, avoid_replans=0, quiet_until=0, mission=len(steps))
            self._mission_next(); return True
        self.walk_task = self.walk_stats = dict(path=collections.deque(path), goal=free, next=self.clock(), first=True, replans=0, tick=0, wait=0, npcwait=0, npcwait_total=0, avoid_replans=0, quiet_until=0, said={})
        if not path: self.walk_task = None; self._walk_done("arrived")
        return True

    ITEM_VALUE = {"GRALATS": {0: 1, 1: 5, 2: 30, 19: 100}, "BOMBS": {3: 5}, "ARROWS": {4: 5}, "GLOVEPOWER": {6: 1, 16: 2}}

    def item_total(self, prop):
        """How much of `prop` the ground items of this level offer (rupees by colour, 5 bombs, 5 arrows per pickup)."""
        vals = self.ITEM_VALUE.get(prop, {})
        return float(sum(vals.get(i["type"], 0) for i in self.items if i["cell"] == self.cell and i["level"] == self.level_name))

    @staticmethod
    def _wname(n): return re.sub(r"^[-*!]+", "", n.strip()).lower()

    def has_weapon(self, name):
        n = self._wname(name)
        return any(self._wname(k) == n for k in self.weapons) or any(self._wname(k) == n for k in getattr(self.runner, "weapons", ()))

    def add_weapon(self, name):
        """`addweapon` from a script: with a local inventory (offline / simulations) the weapon list changes here; online the server owns it."""
        if getattr(self, "local_inventory", False) and not self.has_weapon(name): self.weapons[self._wname(name)] = b""

    def remove_weapon(self, name):
        if getattr(self, "local_inventory", False):
            n = self._wname(name)
            for k in [k for k in self.weapons if self._wname(k) == n]: del self.weapons[k]

    CHEST_ITEMS = leveldoc.CHEST_ITEMS

    def chest_list(self):
        """The closed chests of this level: [{x, y, item (server item type), gain: {prop: amount}}] (tile coordinates)."""
        out = []
        for c in self.chests.get(self.level_name, []):
            if c.get("opened") or c.get("item") is None: continue
            gain = {prop: vals[c["item"]] for prop, vals in self.ITEM_VALUE.items() if c["item"] in vals}
            out.append(dict(x=c["x"], y=c["y"], item=c["item"], gain=gain))
        return out

    def open_chest(self, x, y):
        """Open the chest at tile (x, y): the server is asked (PLI_OPENCHEST {x}{y}) and sends the item; with a local inventory the item is applied here."""
        for c in self.chests.get(self.level_name, []):
            if (c["x"], c["y"]) == (x, y) and not c.get("opened") and c.get("item") is not None:
                self.send(gline(20, gchar(x) + gchar(y))); c["opened"] = True
                if getattr(self, "local_inventory", False):
                    for prop, vals in self.ITEM_VALUE.items():
                        if c["item"] in vals: self.me[prop] = max(self.me.get(prop, 0), vals[c["item"]]) if prop == "GLOVEPOWER" else self.me.get(prop, 0) + vals[c["item"]]
                return True
        return False

    def acquire_plan(self, items, weapons, now, local_only=False):
        """Steps that bring the inventory to `items` ({prop: amount}) and the weapon list to `weapons`, from what the level offers: ground items, chests
        and NPCs that give or sell (found by simulation: `NpcRuntime.sources`). Money is gathered before anything is bought. None if it cannot be done.
        Steps: ("pickup", item, None) / ("get", {..}, None)."""
        need = {p: float(a) for p, a in items.items()}; pre, buy = [], []; have = {p: float(self.me.get(p, 0) or 0) for p in set(need) | {"GRALATS"}}
        sources = self.npcrt.sources(now)
        for wname in weapons:
            if self.has_weapon(wname): continue
            src = next((x for x in sources if any(self._wname(w) == self._wname(wname) for w in x["weapons"]) and all(have.get(p, float(self.me.get(p, 0) or 0)) + (self.item_total(p) if not local_only else 0) >= a for p, a in x["cost"].items())), None)
            if src is None: return None
            for p, a in src["cost"].items(): need[p] = need.get(p, 0.0) + a; have.setdefault(p, float(self.me.get(p, 0) or 0))
            buy.append(("get", dict(src=src, check=("weapon", wname)), None))
        sx, sy = self._gpos(); chests = self.chest_list(); used_src = set()
        done = set()
        while True:
            pending = sorted((p for p in need if p not in done), key=lambda p: p == "GRALATS")
            if not pending: break
            prop = pending[0]; done.add(prop); target = need[prop]; got = have.get(prop, float(self.me.get(prop, 0) or 0)); vals = self.ITEM_VALUE.get(prop, {})
            for it in sorted((i for i in self.items if i["cell"] == self.cell and i["level"] == self.level_name and i["type"] in vals), key=lambda i: abs(i["x"] - sx % 1024) + abs(i["y"] - sy % 1024)):
                if got >= target: break
                pre.append(("pickup", it, None)); got += vals[it["type"]]
            for ch in sorted((c for c in chests if prop in c["gain"]), key=lambda c: abs(c["x"] * 16 - sx % 1024) + abs(c["y"] * 16 - sy % 1024)):
                if got >= target: break
                pre.append(("get", dict(chest=ch, check=("item", prop, min(target, got + ch["gain"][prop]))), None)); got += ch["gain"][prop]
            for src in sources:
                if got >= target: break
                g = src["gain"].get(prop, 0)
                if g <= 0 or src["cost"] or id(src) in used_src: continue
                reps = 1 if not src["repeat"] else min(12, int(-(-(target - got) // g)))
                used_src.add(id(src)); pre.append(("get", dict(src=src, check=("item", prop, min(target, got + g * reps))), None)); got += g * reps
            if got < target and prop != "GRALATS":
                for src in sources:
                    g = src["gain"].get(prop, 0)
                    if g <= 0 or not src["cost"] or id(src) in used_src or not src["repeat"] and g < target - got: continue
                    reps = min(12, int(-(-(target - got) // g))); used_src.add(id(src))
                    for p2, a2 in src["cost"].items(): need[p2] = need.get(p2, 0.0) + a2 * reps; have.setdefault(p2, float(self.me.get(p2, 0) or 0))
                    buy.append(("get", dict(src=src, check=("item", prop, target)), None)); got += g * reps
            if got < target: return None
        return pre + buy

    def say_line(self, text):
        """Say a line like the player typing it: the chat bubble, and the chat events of weapons and NPCs (what the viewer does on Enter)."""
        self.say(text); self.runner.broadcast("playerchats", chat=text); self.npcrt.broadcast("playerchats", text)

    def _flag_is_set(self, f): return self.npcrt._flag_set(f)

    def _door_prelude(self, path):
        """Steps to take before walking `path`: for every door the path crosses that needs a flag that is not set yet, the way to get the flag."""
        now = self.clock(); doors = self.npcrt.doors(now); steps = []
        for nid, way in doors.items():
            flags = [f for f in way.get("flags", []) if not self._flag_is_set(f)]
            missing = any(float(self.me.get(p, 0) or 0) < a for p, a in way.get("items", {}).items()) or any(not self.has_weapon(w) for w in way.get("weapons", []))
            if not flags and not missing: continue
            rects = self.coll.npc_rects_of(self, nid)
            if not any(any(q[0] + 16 < rx + rw and q[0] + 32 > rx and q[1] + 32 < ry + rh and q[1] + 48 > ry for rx, ry, rw, rh in rects) for q in path): continue
            if missing: steps += self.acquire_plan(way.get("items", {}), way.get("weapons", []), now) or []
            for f in flags:
                st = self.npcrt.flag_setter(f, now)
                if st is None: continue
                nid2, how, text = st
                steps.append(("say", text, f) if how == "chat" else ("touch", nid2, f))
        return steps

    def _touch_goal(self, nid):
        """A free lattice position (global px) where the player touches NPC `nid` (the NPC runtime's touch rectangle), nearest to us."""
        n = self.npcs.get(nid); inst = self.npcrt.inst.get(nid)
        if n is None or inst is None: return None
        cx, cy = (n.get("GMAPLEVELX", 0), n.get("GMAPLEVELY", 0)) if self.gmap else (0, 0); gx, gy = cx * 1024 + inst.fx.x * 16, cy * 1024 + inst.fx.y * 16
        w, h = self.npcrt._size(inst); sx, sy = self._gpos(); best = None
        for px in range(int(gx - 32) // 8 * 8, int(gx + w - 8) + 8, 8):
            for py in range(int(gy - 56) // 8 * 8, int(gy + h - 24) + 8, 8):
                if gx - 8 <= px + 24 and px + 8 <= gx + w and gy - 8 <= py + 48 and py + 24 <= gy + h and not self._blocked_plan(px, py):
                    d = abs(px - sx) + abs(py - sy)
                    if best is None or d < best[0]: best = (d, px, py)
        return None if best is None else (best[1], best[2])

    KEY_SYM = {0: 0x4000_0052, 1: 0x4000_0050, 2: 0x4000_0051, 3: 0x4000_004F, 4: ord("a"), 5: ord("s"), 6: ord("d")}

    def _way_ready(self, way):
        """Are the flags set and the inventory enough for this door way (what is left is the trigger and the keys)?"""
        return all(self._flag_is_set(f) for f in way.get("flags", [])) and all(float(self.me.get(p, 0) or 0) >= a for p, a in way.get("items", {}).items()) and all(self.has_weapon(w) for w in way.get("weapons", []))

    def _hold_key(self, k, secs=1.5):
        held = self.__dict__.setdefault("_held_keys", {})
        if k not in held and k in self.KEY_SYM: self.input.key(self.KEY_SYM[k], True)
        if k in self.KEY_SYM: held[k] = self.clock() + secs

    def _keys_tick(self, now=None):
        held = self.__dict__.get("_held_keys")
        if not held: return
        now = now or self.clock()
        for k in [k for k, t in held.items() if t <= now]: del held[k]; self.input.key(self.KEY_SYM[k], False)

    def _door_action(self, w, nxt, now):
        """The next step is blocked by a door NPC that is (or will be) out of the way once its condition is met: say its chat line, hold its keys,
        do its grab / pull / push / lift (the NPC's `action...` event with the player facing it) - each once per 4 s per door."""
        if not getattr(self, "door_commands", True): return
        for nid in self._moving_ids():
            rects = self.coll.npc_rects_of(self, nid)
            if not any(nxt[0] + 16 < rx + rw and nxt[0] + 32 > rx and nxt[1] + 32 < ry + rh and nxt[1] + 48 > ry for rx, ry, rw, rh in rects): continue
            way = self.npcrt.door_way(nid, now)
            if not way or not self._way_ready(way): continue
            for k in way.get("keys", []): self._hold_key(k)
            said = w.setdefault("said", {})
            if now - said.get(nid, -99.0) < 4.0: continue
            if way["how"] == "chat": said[nid] = now; self.say_line(way["text"])
            elif way["how"] == "hit":
                said[nid] = now; d = pathing.direction(self._gpos(), nxt); self.me["SPRITE"] = {"U": 0, "L": 1, "D": 2, "R": 3}[d]; self.attack()
            elif way["how"] == "shot":
                said[nid] = now; d = pathing.direction(self._gpos(), nxt); self.me["SPRITE"] = {"U": 0, "L": 1, "D": 2, "R": 3}[d]
                gx_, gy_ = self._gpos(); cx_, cy_ = self.cell if self.gmap else (0, 0)
                self.proj.shoot((gx_ + 24) / 16 - cx_ * 64, (gy_ + 40) / 16 - cy_ * 64, 0.5, {"R": 0.0, "U": math.pi / 2, "L": math.pi, "D": 1.5 * math.pi}[d], 0.0, 0, "arrow", [])
            elif way["how"] == "carry":
                said[nid] = now; d = pathing.direction(self._gpos(), nxt); self.me["SPRITE"] = {"U": 0, "L": 1, "D": 2, "R": 3}[d]; self.lift()
            elif way["how"] == "bomb":
                said[nid] = now + 4.0; cx_, cy_ = self.cell if self.gmap else (0, 0); self.bombs.put((nxt[0] - cx_ * 1024) / 16, (nxt[1] - cy_ * 1024) / 16, 1)
            elif way["how"] == "action":
                said[nid] = now; d = pathing.direction(self._gpos(), nxt); self.me["SPRITE"] = {"U": 0, "L": 1, "D": 2, "R": 3}[d]
                self._hold_key(4, 0.4); inst = self.npcrt.inst.get(nid)
                if inst is not None: self.npcrt.run(inst, "action" + way["name"])

    def _mission_next(self):
        m = self.mission
        if not m["steps"]:
            final = m["final"]; self.mission = None; self.walk_to(*final, _final=True); return
        kind, a, f = m["steps"].popleft(); now = self.clock()
        if kind == "say": self.say_line(a); m["await_flag"] = (f, now + 2.0); return
        if kind == "get": return self._get_start(a)
        if kind == "pickup":
            if a not in self.items: return self._mission_next()
            m["sub"] = (None, None, now)
            if not self.walk_to((a["x"] - 16) / 16, (a["y"] - 32) / 16, None, _final=True): self.mission = None
            return
        goal = self._touch_goal(a)
        if goal is None: self.mission = None; self.cancel_walk("blocked"); return
        m["sub"] = (a, f, now); tcx, tcy = goal[0] // 1024, goal[1] // 1024
        if not self.walk_to((goal[0] - tcx * 1024) / 16, (goal[1] - tcy * 1024) / 16, (tcx, tcy) if self.gmap else None, _final=True): self.mission = None

    def _get_ok(self, chk):
        return float(self.me.get(chk[1], 0) or 0) >= chk[2] if chk[0] == "item" else self.has_weapon(chk[1])

    def _get_start(self, g):
        """A mission step that obtains something: a chest (walk next to it, open it), an NPC that gives or sells (touch it, say its line, grab it) - repeated
        until the inventory / weapon list shows the result (`check`), at most `tries` times."""
        m = self.mission; now = self.clock(); m["get"] = dict(g, until=now + 12.0, next=0.0, tries=0)
        if g.get("chest"): c = g["chest"]; spot = (c["x"], c["y"] + 2)
        elif g["src"]["how"] == "chat": return m.update(await_get=True)
        else:
            goal = self._touch_goal(g["src"]["nid"])
            if goal is None: self.mission = None; self.cancel_walk("blocked"); return
            tcx, tcy = goal[0] // 1024, goal[1] // 1024; spot = ((goal[0] - tcx * 1024) / 16, (goal[1] - tcy * 1024) / 16)
        cell = (goal[0] // 1024, goal[1] // 1024) if not g.get("chest") and self.gmap else None
        m["sub"] = (None, "get", now)
        if not self.walk_to(spot[0], spot[1], cell, _final=True): self.mission = None

    def _get_tick(self, now):
        m = self.mission; g = m["get"]
        if self._get_ok(g["check"]): m["get"] = None; m["await_get"] = None; return self._mission_next()
        if now >= g["until"] or g["tries"] >= 14: self.mission = None; return self._walk_done("blocked")
        if now < g["next"]: return
        g["next"] = now + 0.6; g["tries"] += 1
        if g.get("chest"): self.open_chest(g["chest"]["x"], g["chest"]["y"]); g["next"] = now + 1.5
        else:
            src = g["src"]; inst = self.npcrt.inst.get(src["nid"])
            if src["how"] == "touch":
                if g["tries"] > 1 and inst is not None: self.npcrt.run(inst, "playertouchsme")
            elif src["how"] == "chat": self.say_line(src["text"])
            elif src["how"] == "action" and inst is not None: self.npcrt.run(inst, "action" + src["name"])

    def _mission_tick(self, now=None):
        m = getattr(self, "mission", None)
        if not m: return
        now = now or self.clock()
        if m.get("await_get"): return self._get_tick(now)
        if m["await_flag"]:
            f, until = m["await_flag"]
            if self._flag_is_set(f) or now >= until: m["await_flag"] = None; self._mission_next()
        elif m["sub"] and not getattr(self, "walk_task", None):
            nid, f, t0 = m["sub"]
            if f == "get":
                if getattr(self, "walk_result", "") == "arrived": m["sub"] = None; m["await_get"] = True; m["get"]["until"] = now + 12.0
                else: self.mission = None; self._walk_done("blocked")
            elif getattr(self, "walk_result", "") == "arrived" and f is None: m["sub"] = None; self._mission_next()
            elif getattr(self, "walk_result", "") == "arrived":
                m["await_flag"] = (f, now + 1.5); m["sub"] = None
            else: self.mission = None; self._walk_done("blocked")

    def walking_to(self): return getattr(self, "walk_task", None) is not None or getattr(self, "mission", None) is not None
    def cancel_walk(self, result="cancelled"):
        had = self.walking_to(); self.walk_task = None; self.mission = None
        if had: self.stop()
        self._walk_done(result)
    def _walk_done(self, result):
        if self.carrying is not None and not getattr(self, "mission", None): self.throw()
        self.walk_result = result; cb = getattr(self, "on_walk_done", None)
        if cb and not getattr(self, "mission", None): cb(result)

    def _walk_tick(self, now=None):
        w = getattr(self, "walk_task", None)
        if not w: return
        now = now or self.clock(); n = 0
        while w["next"] <= now and n < 4 and self.walk_task is w:
            n += 1; w["next"] += 0.05
            if not w["path"]:
                self.walk_task = None; self.stop(); self._walk_done("arrived"); return
            nxt = w["path"][0]; before = self._gpos(); w["tick"] += 1
            if getattr(self, "avoid_players", True):
                if w["tick"] % 4 == 0 and now >= w["quiet_until"] and w["avoid_replans"] < 60:
                    others = self.others_global(); dcost_, dtcost_ = self._dynamic_costs(others)
                    price = (lambda q, i: dtcost_(q[0], q[1], i + 1)) if dtcost_ else (lambda q, i: dcost_(*q)) if dcost_ else None
                    cost, tcost = self._plan_costs(others)
                    if price and any(price(q, i) for i, q in enumerate(list(w["path"])[:12])):
                        w["avoid_replans"] += 1; p = pathing.find_path(self._blocked_plan, before, w["goal"], cost=cost, tcost=tcost)
                        if p is not None:
                            w["path"].clear(); w["path"].extend(p); nxt = w["path"][0] if p else nxt
                            if any(price(q, i) for i, q in enumerate(list(w["path"])[:12])): w["quiet_until"] = now + 1.0
                if w["path"]:
                    nxt = w["path"][0]; hard = self.AVOID_HARD
                    if w["wait"] < 30 and any(abs(nxt[0] - ox) < hard and abs(nxt[1] - oy) < hard for ox, oy in self.others_global()):
                        w["wait"] += 1; continue
                w["wait"] = 0
            pushing = False
            if w["path"] and self.push_npcs and self._blocked_g(*nxt):
                cx_, cy_ = self.cell if self.gmap else (0, 0); bl = self.coll.blockers(self, nxt[0] - cx_ * 1024, nxt[1] - cy_ * 1024)
                pushing = bool(bl) and all(self.npcrt.inst.get(i) and self._pushy(self.npcrt.inst[i]) for i in bl) and not self.coll.blocked(self, nxt[0] - cx_ * 1024, nxt[1] - cy_ * 1024, skip=set(bl))
            if w["path"] and not pushing and self._blocked_g(*nxt) and not self._blocked_plan(*nxt):
                self._door_action(w, nxt, now)
            if w["path"] and not pushing and w.get("npcwait", 0) < 80 and self._blocked_g(*nxt) and not self._blocked_plan(*nxt):
                w["npcwait"] = w.get("npcwait", 0) + 1; w["npcwait_total"] += 1; continue
            w["npcwait"] = 0
            self.step(pathing.direction(before, nxt), w["first"], use_links=False); w["first"] = False
            if self._gpos() == nxt: w["path"].popleft(); continue
            if w["replans"] < 2:
                w["replans"] += 1; p = pathing.find_path(self._blocked_g, self._gpos(), w["goal"])
                if p: w["path"].clear(); w["path"].extend(p); continue
            self.walk_task = None; self.stop(); self._walk_done("blocked"); return

    def teleport(self, x_tiles, y_tiles, cell=None, check=True):
        """A server-commanded move inside the current level, or to another cell of the gmap: local tile position (+ gmap cell).
        Sends the same player props a walking client sends, so the game server and the other players follow."""
        x, y = max(0, min(1023, int(x_tiles * 16))), max(0, min(1023, int(y_tiles * 16)))
        if check:
            spot = self.free_spot(x / 16, y / 16, cell if cell is not None and self.gmap else None)
            if spot is None: return False
            x, y = max(0, min(1023, spot[0])), max(0, min(1023, spot[1]))
        self.cancel_walk("cancelled") if self.walking_to() else None
        rows = self.gmap_rows() if self.gmap else None
        if cell is not None and rows and tuple(cell) != tuple(self.cell):
            cx, cy = int(cell[0]), int(cell[1])
            if 0 <= cy < len(rows) and 0 <= cx < len(rows[0]):
                self.me["GMAPLEVELX"], self.me["GMAPLEVELY"] = cx, cy; self.map_cell = (cx, cy); self.level_name = rows[cy][cx]; self.pos = (x, y)
                self.send(gline(2, gchar(43) + gchar(cx) + gchar(44) + gchar(cy) + gchar(78) + enc_pos(x) + gchar(79) + enc_pos(y))); self.ensure_neighbours()
                return True
            return False
        self.pos = (x, y); self.send(gline(2, gchar(PROP_X2) + enc_pos(x) + gchar(PROP_Y2) + enc_pos(y))); return True

    @property
    def cell(self):
        """(col,row) of the current sub-level inside the gmap, from our own GMAPLEVELX/Y props."""
        if "GMAPLEVELX" in self.me and "GMAPLEVELY" in self.me: return (self.me["GMAPLEVELX"], self.me["GMAPLEVELY"])
        return self.map_cell or (0, 0)

    def snapshot(self):
        me = dict(self.me); me["X2"], me["Y2"] = self.pos
        if me.get("MESSAGE") and time.time() - getattr(self, "say_time", 0) < 6: me["MESSAGE_SHOWN"] = me["MESSAGE"]
        now = time.time()
        self.items = [i for i in self.items if now - i["t0"] < ITEM_LIFETIME and i["level"] == self.level_name]
        items = [dict(type=i["type"], x=i["x"], y=i["y"], cx=i["cell"][0], cy=i["cell"][1]) for i in self.items]
        return dict(levels=self.levels, npcs=self.npcs, weapons=self.weapons, me=me, gmap=self.gmap, level=self.level_name,
                    players=dict(self.players), items=items, imgs=dict(self.imgs), effect=self.effect, texts=dict(self.texts), polys=dict(self.polys),
                    sign=self.sign[0] if time.time() < self.sign[1] else "", fx=self.npcrt.fx, horses=list(self.horses), hud_hidden=self.hud_hidden, adjacent=self.adjacent_levels(), projectiles=self.proj.view(), focus=getattr(self, "focus", None), bombfx=self.bombs.view(), tiledef_memory=list(self.__dict__.get("tiledef_memory", ())), npc_rev=getattr(self, "npc_rev", 0))

    def level_meta(self, name):
        """gs2emu with an NPC-server keeps links and signs to itself (it warps you and shows the signs), so the client never hears of them. They are in the level file:
        fetch it (like any other file) and read its LINK / SIGN lines. -> dict(links=[[level, x, y, w, h, dx, dy] as strings], signs=[(x, y, text)]) or None until the file is here."""
        lv = self.levels.get(name)
        if lv is None: return None
        if lv.meta is not None: return lv.meta
        now = time.time()
        if now - lv.meta_try < 1.0: return None
        lv.meta_try = now
        import assets, nwlevel
        p = assets.find(name, level=True)
        if not p: return None
        try: nw = nwlevel.load_nw(p)
        except Exception: lv.meta = dict(links=[], signs=[]); return lv.meta
        lv.meta = dict(links=[[l["level"], str(l["x"]), str(l["y"]), str(l["w"]), str(l["h"]), str(l["nx"]), str(l["ny"])] for l in nw.links], signs=[(s_["x"], s_["y"], s_["text"]) for s_ in nw.signs])
        return lv.meta

    def adjacent_levels(self):
        """A level that is not on a gmap touches its neighbours through edge links (a one-tile strip along an edge, `playerx` / `playery` along it): the levels that
        Graal draws next to this one. [(name, offset x, offset y)] in tiles, the neighbour's origin relative to ours (a link at x=0 to x=61 puts it 61 tiles to the left)."""
        lv = self.levels.get(self.level_name)
        if self.gmap or not lv: return []
        links = lv.links or ((self.level_meta(self.level_name) or {}).get("links") or [])
        if not links: return []
        memo = self.__dict__.setdefault("_adj_memo", {}); key = (self.level_name, len(links))
        if key in memo: return memo[key]
        out = []
        for l in links:
            try: x, y, w, h = (float(v) for v in l[1:5]); dx, dy = l[5], l[6]
            except (ValueError, IndexError): continue
            if not ((h == 1 and w >= 32 and y in (0, 63)) or (w == 1 and h >= 32 and x in (0, 63))): continue
            # Only a link that keeps the coordinate along its edge (playerx on a top / bottom edge, playery on a left / right one) joins two
            # levels side by side. One to a fixed spot is a door: laboo1's bottom edge goes to worldmap_b3 at 60.5,55, and taking it as a
            # neighbour put the worldmap 59.5 tiles to the left, where the player could walk into it - and was saved at x -11.5 in laboo1.
            if (h == 1 and dx != "playerx") or (w == 1 and dy != "playery"): continue
            off = lambda own, v: 0.0 if v in ("playerx", "playery") else own - float(v)
            try: out.append((l[0], off(x, dx), off(y, dy)))
            except ValueError: pass
        memo[key] = out; return out

    def current_links(self):
        lv = self.levels.get(self.level_name)
        out = []
        for l in (lv.links if lv else []):
            try:
                out.append(dict(level=l[0], x=float(l[1]), y=float(l[2]), w=float(l[3]), h=float(l[4]), dx=l[5], dy=l[6]))
            except (ValueError, IndexError): pass
        return out

    def link_at(self, px=None, py=None):
        px, py = (px, py) if px is not None else self.pos
        cx, cy = (px + 16) / 16, (py + 24) / 16
        rows = self.gmap_rows(); in_gmap = {n for r in rows for n in r} if rows else set()
        for l in self.current_links():
            if l["level"] in in_gmap: continue
            if l["x"] <= cx < l["x"] + l["w"] and l["y"] <= cy < l["y"] + l["h"]: return l
        return None

    def take_link(self, link):
        """Client-side link: send PLI_LEVELWARP {GCHAR x*2}{GCHAR y*2}{level} (the server multiplies by 8 px)."""
        def dest(v, own): return own / 16 if v in ("playerx", "playery") else float(v)
        tx, ty = dest(link["dx"], self.pos[0]), dest(link["dy"], self.pos[1])
        self.log.append(f"warp via link -> {link['level']} at {tx},{ty}")
        if (self.me.get("GANI") or "").split(",")[0] == self.resolve_ani("walk") and time.time() >= self.weapon_ani_until:
            n = self.move_gani("idle"); self.me["GANI"] = n; self.send(gline(2, gchar(PROP_GANI) + gstr(n.encode())))   # a script's walk (a ladder) ends here
        self._enter_world(link["level"]); self.level_name = None; self.gmap = None; self.map_cell = None
        nb = self.levels.get(link["level"]); self.warp(link["level"], tx * 16, ty * 16)
        if nb is not None and nb.board: self.level_name = link["level"]

    def step_cell(self):
        """gmap: when walking over a sub-level edge, wrap local x/y and tell the server the new cell (props 43/44)."""
        x, y = self.pos; cx, cy = self.cell; moved = False
        if self._next_cell(x, y) is None: return False
        if x < 0: cx -= 1; x += 1024; moved = True
        elif x >= 1024: cx += 1; x -= 1024; moved = True
        if y < 0: cy -= 1; y += 1024; moved = True
        elif y >= 1024: cy += 1; y -= 1024; moved = True
        if moved:
            self.pos = (x, y); self.me["GMAPLEVELX"], self.me["GMAPLEVELY"] = cx, cy; self.map_cell = (cx, cy)
            rows = self.gmap_rows()
            if rows and 0 <= cy < len(rows) and 0 <= cx < len(rows[0]): self.level_name = rows[cy][cx]
            self.send(gline(2, gchar(43) + gchar(cx) + gchar(44) + gchar(cy) + gchar(78) + enc_pos(x) + gchar(79) + enc_pos(y)))
        return moved

    def _next_cell(self, x, y):
        """The gmap cell local position (x, y) lies in when it is past the edge of ours, if that cell exists; else None
        (inside our cell, on a plain level, or past the outer edge of the gmap). Before the map file has arrived its size is unknown: any
        cell that is not negative is let through (only a negative one is harmful: the server stores it as 255)."""
        if (0 <= x < 1024 and 0 <= y < 1024) or not self.gmap: return None
        cx, cy = self.cell
        cx += -1 if x < 0 else 1 if x >= 1024 else 0; cy += -1 if y < 0 else 1 if y >= 1024 else 0
        if cx < 0 or cy < 0: return None
        rows = self.gmap_rows()
        if rows and (cy >= len(rows) or cx >= len(rows[cy])): return None
        return (cx, cy)

    def off_world(self, x, y):
        """gmap: True when local position (x, y) is too far past the outer edge of the whole map. Like Graal, the player may lean over it
        as long as the wall box at the feet stays inside: that is how links on the outer rows/columns are reached. A cell past the edge must
        never be sent: the server stores it as one unsigned byte (-1 -> 255) and the next login got no level.
        A plain level is left to the collision code: it knows the neighbours joined by edge links, and those links are taken by walking over the edge."""
        if not self.gmap: return False
        bx, by, bw, bh = collision.BOX; x0, y0, x1, y1 = x + bx, y + by, x + bx + bw - 1, y + by + bh - 1
        return any(not (0 <= px < 1024 and 0 <= py < 1024) and self._next_cell(px, py) is None for px, py in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)))

    def tile_table(self, level_name):
        """The tile type table (tiletypes.TYPE0 or TYPE1) for a level, from its addtiledef type (render.tileset_type); cached until NPC scripts,
        the TileDefs weapon or the remembered tiledefs change."""
        import render
        from tiletypes import TYPE0, TYPE1
        mem = self.__dict__.get("tiledef_memory", {})
        tw = self.weapons.get("TileDefs", b"")
        key = (level_name, id(tw), len(tw), getattr(self, "npc_rev", 0), len(mem), self.gmap)   # id: a new TileDefs weapon is a new bytes object
        cache = self.__dict__.setdefault("_tile_tables", {})
        if key in cache: return cache[key]
        tdefs = tw.replace(b"\xa7", b"\n").decode("latin1")
        own, other = [], list(mem)
        cell = None
        if self.gmap:
            rows = self.gmap_rows() or []
            cell = next(((x, y) for y, r in enumerate(rows) for x, n in enumerate(r) if n == level_name), None)
        for n in self.npcs.values():
            sc = n.get("SCRIPT")
            if not sc or "tiledef" not in sc: continue
            mine = (cell is not None and (n.get("GMAPLEVELX"), n.get("GMAPLEVELY")) == cell) if self.gmap else level_name == self.level_name
            (own if mine else other).append(sc)
        table = TYPE1 if render.tileset_type(level_name, tdefs, own, other) == 1 else TYPE0
        if len(cache) > 64: cache.clear()
        cache[key] = table; cache.setdefault("_keep", []).append(tw)   # keep the bytes alive so its id is not reused while the key is cached
        return table

    def gmap_rows(self):
        if not self.gmap: return None
        import render
        return render.read_gmap(self.gmap)


    def poll(self):
        """Read whatever the server has sent without waiting, update the model, send heartbeats."""
        if not getattr(self, "_guild_asked", False) and self.level_name:   # once after login: which guilds are we in (for #g and the guild window)
            self._guild_asked = True
            try: self.guild_cmd("info")
            except (OSError, AttributeError): self._guild_asked = False
        sock = self.conn.sock; sock.setblocking(False)
        try:
            while True:
                data = sock.recv(65536)
                if not data: raise ConnectionError("server closed the connection")
                self.frames += 1
                for t, plain in self.conn.rx.feed(data):
                    for item in self.lp.feed(plain): self.safe_handle(*item)
        except (BlockingIOError, InterruptedError): pass
        self.heartbeat(); self.tick_all()

    def ensure_neighbours(self):
        """gmap: request the sub-levels around our cell that we do not have yet (once each)."""
        rows = self.gmap_rows(); asked = self.__dict__.setdefault("_asked", set())
        if not self.gmap:
            for n, _, _ in self.adjacent_levels():
                if n not in asked and not (n in self.levels and self.levels[n].board): self.request_level(n)
                asked.add(n)
            return
        if not rows: return
        cx, cy = self.cell
        for dy in (-2, -1, 0, 1, 2):
            for dx in (-2, -1, 0, 1, 2):
                x, y = cx + dx, cy + dy
                if 0 <= y < len(rows) and 0 <= x < len(rows[0]):
                    n = rows[y][x]
                    if n not in asked and not (n in self.levels and self.levels[n].board): self.request_level(n)
                    asked.add(n)

    push_npcs = True

    def _push(self, direction, x, y):
        """The player walks into NPC shapes: if every NPC in the way is pushable (`canbepushed`), nothing else blocks the step, and each NPC can move
        8 px in the walking direction (no wall or other NPC shape behind it), they move and the step goes on. Client side only: the server is not told."""
        if not self.push_npcs: return False
        ids = self.coll.blockers(self, x, y)
        if not ids or any(not (self.npcrt.inst.get(i) and self.npcrt.inst[i].fx.pushable) for i in ids): return False
        if self.coll.blocked(self, x, y, skip=set(ids)): return False
        dx, dy = {"L": (-8, 0), "R": (8, 0), "U": (0, -8), "D": (0, 8)}[direction]; moves = []
        for i in ids:
            rects = self.coll.npc_rects_of(self, i)
            if any(self.coll.rect_blocked(self, (rx + dx, ry + dy, rw, rh), ignore=set(ids)) for rx, ry, rw, rh in rects): return False
            moves.append(i)
        for i in moves:
            n = self.npcs[i]; inst = self.npcrt.inst[i]; n["X2"] += dx; n["Y2"] += dy; inst.src = (n["X2"], n["Y2"]); inst.fx.x += dx / 16; inst.fx.y += dy / 16
        self.npcrt.version += 1
        for i in moves: self.send_npc_pos(i)
        return True

    EVENT_GAP = 0.35

    def _pushed_event(self, direction, x, y):
        """Walking into an NPC whose script has `actionpushed` (the canpush-canpull class): fire it, at most every 0.35 s per NPC, when the NPC has room to move."""
        now = self.clock(); last = self.__dict__.setdefault("_ev_last", {})
        dx, dy = {"L": (-16, 0), "R": (16, 0), "U": (0, -16), "D": (0, 16)}[direction]
        for nid in self.coll.blockers(self, x, y):
            inst = self.npcrt.inst.get(nid)
            if inst is None or "actionpushed" not in inst.alllow or now - last.get((nid, "p"), -9.0) < self.EVENT_GAP: continue
            rects = self.coll.npc_rects_of(self, nid)
            if any(self.coll.rect_blocked(self, (rx + dx, ry + dy, rw, rh), ignore={nid}) for rx, ry, rw, rh in rects): continue
            last[(nid, "p")] = now; self.npcrt.run(inst, "actionpushed")

    PUSH_POINT = {0: (1.5, 0.5), 1: (0.0, 2.0), 2: (1.5, 3.5), 3: (3.0, 2.0)}

    def moved_by_script(self):
        """A script set playerx / playery (the Click Warp staff: `playerx = mousex`). Like a step: move into the gmap cell the spot lies in if it
        exists, keep the player inside the map otherwise (a click past the outer edge left them where no step could get back), and tell the server."""
        if self.step_cell(): self.ensure_neighbours(); return
        x, y = self.pos
        if self.off_world(x, y) or (not self.gmap and not (-16 <= x <= 1008 and -32 <= y <= 1008)):
            x, y = min(max(x, 0), 1008), min(max(y, 0), 1008); self.pos = (x, y)
        self.send(gline(2, gchar(PROP_X2) + enc_pos(x) + gchar(PROP_Y2) + enc_pos(y)))
        # A link where the script put the player is taken, as in Graal: a ladder (world_ladder) moves the player up into the link at its top.
        link = self.link_at()
        if link: self.take_link(link)

    def _corner_slide(self, direction, x, y):
        """The step to (x, y) is blocked, but half a step (8 px) to the side the way is open: slide sideways now, like Graal, so the next step goes
        through. Paths one tile wide (the worldmap is mostly that) are otherwise only walkable from exactly the right half-tile. -> new position or None."""
        px, py = self.pos
        sides = ((8, 0), (-8, 0)) if direction in "UD" else ((0, 8), (0, -8))
        sides = sorted(sides, key=lambda o: ((px + o[0]) % 16, (py + o[1]) % 16) != (0, 0))   # prefer the side that lines the box up with the tiles
        for ox, oy in sides:
            sx, sy = px + ox, py + oy
            if not self.coll.blocked(self, x + ox, y + oy) and not self.coll.blocked(self, sx, sy) and not self.off_world(sx, sy) and not self.off_world(x + ox, y + oy):
                return (sx, sy)
        return None

    def _out_of_wall(self, x, y):
        """The player stands inside a wall (a warp or link put them there: the cave teleporter in worldmap_b5, the doors of several portwolfe
        buildings drop you on wall tiles, sometimes deep inside them) and the step to (x, y) does not make that overlap bigger and touches no
        NPC: allow it, as the original client does, or every direction stays blocked for ever. Once on the way out, going back in is refused."""
        here = self.coll.wall_overlap(self, *self.pos)
        let_go = getattr(self, "_let_go", None)   # (NPC id, time) of the last detachplayer
        npcs_here = {k: v for k, v in self.coll.npc_overlap(self, *self.pos).items() if let_go and k == let_go[0] and self.clock() - let_go[1] < 3.0}
        if here <= 0 and not npcs_here: return False
        if self.coll.wall_overlap(self, x, y) > here: return False
        # A ladder blocks (setshape 1) and lets the player go at its top while the player still overlaps it: for a few seconds the step may take
        # the player further out of the NPC that let go, touching no other one. Other NPC shapes block as always (a cart rolling onto a walker).
        there = self.coll.npc_overlap(self, x, y)
        return all(k in npcs_here and v < npcs_here[k] for k, v in there.items())

    def _send_pushed(self, d, x, y):
        """Walking into an NPC online: PLI_TRIGGERACTION `pushed,<dir>` at the point in front of the player (what `FUN_0053e7a8` sends in Graal_222.exe).
        The server turns it into the event `actionpushed` of the NPC there (the server-side canpush-canpull class moves the NPC, and everyone sees it).
        The server ignores PLI_NPCPROPS from clients when it runs an NPC-server, so this is the only way a push reaches the other players."""
        if getattr(self, "local_inventory", False): return False
        if not any(isinstance(i, int) for i in self.coll.blockers(self, x, y)): return False
        now = self.clock(); last = self.__dict__.setdefault("_ev_last", {})
        if now - last.get("push_sent", -9.0) < self.EVENT_GAP: return False
        last["push_sent"] = now; dx, dy = self.PUSH_POINT[d & 3]
        self.send_triggeraction(0, self.pos[0] / 16 + dx, self.pos[1] / 16 + dy, ["pushed", str(d & 3)]); self.pushed_sent = getattr(self, "pushed_sent", 0) + 1
        return True

    PULL_POINT = {0: (1.5, 0.0), 1: (-0.5, 2.0), 2: (1.5, 4.0), 3: (3.5, 2.0)}
    STEP_BACK = {0: (0, -1), 1: (-1, 0), 2: (0, 1), 3: (1, 0)}

    def _hold_gani(self, name):
        """The pose while the grab key is held: `grab` (or `grabz` when the server only has that), and `pull` while pulling backwards. Sent as the gani prop."""
        n = self.resolve_ani(name)
        if ganimod.load(n) is None and name == "grab" and ganimod.load("grabz") is not None: n = "grabz"
        if time.time() < self.weapon_ani_until or self.attacking(): return
        if self.me.get("GANI") == n and time.time() - self.gani_start < 0.5: return
        self.me["GANI"] = n; self.gani_start = time.time(); self.send(gline(2, gchar(PROP_GANI) + gstr(n.encode())))

    def holding_pose(self):
        """Is the player in the grab / pull pose (so that releasing A should return to idle)?"""
        return (self.me.get("GANI") or "").split(",")[0] in {self.resolve_ani("grab"), "grabz", self.resolve_ani("pull")}

    def _npcs_in_front(self):
        """NPCs whose body overlaps the sword box: their shape, or - for a server NPC whose shape only the server knows - their image."""
        sr = self.sword_rect(); out = []
        for nid, inst in list(self.npcrt.inst.items()):
            rects = self.coll.npc_rects_of(self, nid)
            name = inst.fx.image or (self.npcs.get(nid) or {}).get("IMAGE")
            if not rects and isinstance(nid, int) and name and name != "#c#" and not inst.fx.hidden:
                import render; im = render.load_image(name); gx, gy = self.npcrt._gpos(inst)
                if im is not None: rects = [(gx, gy, im.width, im.height)]
            if any(sr[0] < q[0] + q[2] and sr[0] + sr[2] > q[0] and sr[1] < q[1] + q[3] and sr[1] + sr[3] > q[1] for q in rects): out.append(nid)
        return out

    def _send_action(self, name, d, point):
        """Online: PLI_TRIGGERACTION `<name>,<dir>` at `point` in front of the player; the server runs `action<name>` of the NPC there. At most every 0.35 s."""
        if getattr(self, "local_inventory", False): return False
        now = self.clock(); last = self.__dict__.setdefault("_ev_last", {})
        if now - last.get(name + "_sent", -9.0) < self.EVENT_GAP: return False
        last[name + "_sent"] = now; dx, dy = point
        self.send_triggeraction(0, self.pos[0] / 16 + dx, self.pos[1] / 16 + dy, [name, str(d & 3)]); return True

    def _pull(self, direction):
        """Holding the grab key (A) in front of an NPC and walking backwards pulls it (Graal_222.exe FUN_00531110): the client tells the server `pulled,<dir>` (online) and
        fires `actionpulled` on local NPCs; an NPC with `canbepulled` follows one tile toward the player (if there is room for both) and gets `waspulled`."""
        if not self.input.is_down(4): return False
        d = self.me.get("SPRITE", 2) & 3; face = "ULDR"[d]
        if direction != {"U": "D", "D": "U", "L": "R", "R": "L"}[face]: return False
        now = self.clock(); last = self.__dict__.setdefault("_ev_last", {}); ids = self._npcs_in_front(); held = False
        self._send_action("pulled", d, self.PULL_POINT[d])
        if any(isinstance(i, int) for i in ids): held = True
        if not held and (ids or self.coll.rect_blocked(self, self.sword_rect())): held = True
        for nid in ids:
            inst = self.npcrt.inst.get(nid)
            if inst is None or now - last.get((nid, "u"), -9.0) < self.EVENT_GAP: held = held or inst is not None and ("actionpulled" in inst.alllow or inst.fx.pullable); continue
            if "actionpulled" in inst.alllow: last[(nid, "u")] = now; self.npcrt.run(inst, "actionpulled"); held = True
            elif inst.fx.pullable and self._pull_npc(nid, inst, d): last[(nid, "u")] = now; held = True
        if held: self._hold_gani("pull")
        return held

    def _pull_npc(self, nid, inst, d):
        dx, dy = self.STEP_BACK[d]; sx, sy = -dx * 16, -dy * 16
        for rx, ry, rw, rh in self.coll.npc_rects_of(self, nid):
            if self.coll.rect_blocked(self, (rx + sx, ry + sy, rw, rh), ignore={nid}): return False
        x, y = self.pos[0] + sx, self.pos[1] + sy
        if self.off_world(x, y) or self.coll.blocked(self, x, y, skip={nid}): return False
        n = self.npcs[nid]; n["X2"] += sx; n["Y2"] += sy; inst.src = (n["X2"], n["Y2"]); inst.fx.x += sx / 16; inst.fx.y += sy / 16
        self.pos = (x, y); self.npcrt.version += 1
        if self.step_cell(): self.send(gline(2, gchar(PROP_SPRITE) + gchar(d))); self.ensure_neighbours()
        else:
            axis, v = (PROP_X2, x) if dx else (PROP_Y2, y)
            self.send(gline(2, gchar(PROP_GANI) + gstr(self.resolve_ani("walk").encode()) + gchar(PROP_SPRITE) + gchar(d) + gchar(axis) + enc_pos(v)))
        self.send_npc_pos(nid)
        if inst.has("waspulled"): self.npcrt.run(inst, "waspulled")
        return True

    def read_sign(self):
        """A in front of a level sign (a tile pair, x..x+1 / y) shows its text in the message window."""
        lv = self.levels.get(self.level_name)
        signs = (lv.signs if lv is not None else []) or ((self.level_meta(self.level_name) or {}).get("signs") or [])
        if not signs: return False
        cx, cy = self.cell if self.gmap else (0, 0); sr = self.sword_rect()
        for sx, sy, text in signs:
            r = ((cx * 64 + sx) * 16, (cy * 64 + sy) * 16, 32, 16)
            if sr[0] < r[0] + r[2] and sr[0] + sr[2] > r[0] and sr[1] < r[1] + r[3] and sr[1] + sr[3] > r[1] and text.strip():
                self.say2(text.replace("\n", "#b")); return True
        return False

    def grab(self):
        """The grab key (A) was pressed: throw what we carry; else lift a `canbecarried` NPC in front (needs a glove); else the NPC in front hears `actiongrab`
        (local NPCs directly, server NPCs through PLI_TRIGGERACTION `grab,<dir>`). Holding A and walking backwards then pulls (`_pull`)."""
        if self.frozen() or self.attacking(): return False
        if self.carrying is not None: return self.throw()
        if self.lift(): return True
        if self.read_sign(): return True
        d = self.me.get("SPRITE", 2) & 3; self._send_action("grab", d, self.PULL_POINT[d]); did = False; self._hold_gani("grab")
        for nid in self._npcs_in_front():
            inst = self.npcrt.inst.get(nid)
            if inst is not None and "actiongrab" in inst.alllow: self.npcrt.run(inst, "actiongrab"); did = True
        return did

    def send_npc_pos(self, nid):
        """PLI_NPCPROPS {GINT3 id}{X2}{Y2}: tell the server where we put a level NPC (it ignores this when it runs an NPC-server). Only for server NPC ids."""
        n = self.npcs.get(nid)
        if isinstance(nid, int) and n is not None and "X2" in n:
            self.send(gline(3, gint_enc(nid, 3) + gchar(75) + enc_pos(int(n["X2"])) + gchar(76) + enc_pos(int(n["Y2"]))))

    def step(self, direction, first, use_links=True):
        """One 50 ms walking tick in `direction` (8 px). Walls and NPC shapes block; returns a link that was taken, or None."""
        if self._pull(direction): return None
        d = DIRS[direction]; x, y = self.pos; x0, y0 = x, y
        if direction in "LR": x += -8 if direction == "L" else 8
        else: y += -8 if direction == "U" else 8
        owned = time.time() < self.weapon_ani_until
        wname = self.move_gani("walk", x, y).encode()
        head = (b"" if owned else gchar(PROP_GANI) + gstr(wname)) + gchar(PROP_SPRITE) + gchar(d) if first else b""
        if not owned: self.me["GANI"] = wname.decode()
        self.me["SPRITE"] = d
        if self.off_world(x, y):
            if first: self.send(gline(2, head))
            return None
        if self.coll.blocked(self, x, y) and self._out_of_wall(x, y): pass
        elif self.coll.blocked(self, x, y):
            self._send_pushed(d, x, y)
        if self.coll.blocked(self, x, y) and not self._out_of_wall(x, y) and not self._push(direction, x, y):
            side = self._corner_slide(direction, x, y)
            if side is None:
                self._pushed_event(direction, x, y)
                if first: self.send(gline(2, head))
                return None
            x, y = side
        self.pos = (x, y)
        if self.step_cell():
            self.send(gline(2, (b"" if owned else gchar(PROP_GANI) + gstr(wname)) + gchar(PROP_SPRITE) + gchar(d))); self.ensure_neighbours()
        else:
            moved = (gchar(PROP_X2) + enc_pos(x) if x != x0 else b"") + (gchar(PROP_Y2) + enc_pos(y) if y != y0 else b"")
            self.send(gline(2, head + moved))
        self.pickup_items(); self.horse_touch()
        link = self.link_at() if use_links else None
        if link: self.take_link(link)
        return link

    def attack(self):
        """S key (matches the real Graal_222): cut a bush in front (BOARDMODIFY) if there is one, then play the `sword` gani."""
        if not getattr(self, "weapons_enabled", True): return False
        d = self.me.get("SPRITE", 2) & 3
        bush = self.find_bush(); cut = bool(bush and self.cut_bush(*bush))
        sword = self.resolve_ani("sword")
        self.send(gline(2, gchar(PROP_GANI) + gstr(sword.encode()) + gchar(PROP_SPRITE) + gchar(d)))
        self.me["GANI"] = sword; self.gani_start = self.attack_start = time.time()
        g = ganimod.load(sword); self.attack_until = self.attack_start + (ganimod.duration(g) if g else 0.25)
        self.runner.sword_event()
        sr = self.sword_rect(); cx_, cy_ = self.cell if self.gmap else (0, 0); hx, hy = (sr[0] + 16) / 16 - cx_ * 64, (sr[1] + 16) / 16 - cy_ * 64
        if 0 <= hx < 64 and 0 <= hy < 64: self.send(gline(36, gchar(max(1, int(_stat_sword(self)))) + gchar(int(hx * 2)) + gchar(int(hy * 2))))
        self.hit_npcs("washit", lambda q: sr[0] < q[0] + q[2] and sr[0] + sr[2] > q[0] and sr[1] < q[1] + q[3] and sr[1] + sr[3] > q[1])
        return cut

    def horse_touch(self):
        """Walking into a horse (`puthorse`) mounts it: HORSEIMAGE prop set (and sent), the horse leaves the ground."""
        if self.me.get("HORSEIMAGE") or self.clock() < getattr(self, "_no_mount", 0.0): return False
        fx_, fy_ = self.pos[0] + 16, self.pos[1] + 32; cell = self.cell if self.gmap else (0, 0)
        for h in list(self.horses):
            if tuple(h[3]) != tuple(cell): continue
            hx, hy = h[1] * 16, h[2] * 16
            if fx_ < hx + 32 and fx_ + 16 > hx and fy_ < hy + 32 and fy_ + 16 > hy:
                self.horses.remove(h); self.me["HORSEIMAGE"] = h[0]; self.send(gline(2, gchar(21) + gstr(h[0].encode("latin1"))))
                self.send(gline(8, gchar(int(h[1] * 2)) + gchar(int(h[2] * 2))))
                self._set_move_gani()   # ridestill / ride at once
                return True
        return False

    def dismount(self):
        """Get off: the horse stands where the player is, the HORSEIMAGE prop is cleared."""
        name = self.me.get("HORSEIMAGE")
        if not name: return False
        cell = self.cell if self.gmap else (0, 0); self.horses.append((name, self.pos[0] / 16, self.pos[1] / 16 + 0.5, cell, self.me.get("SPRITE", 2) & 3))
        lx, ly = self.pos[0] / 16, self.pos[1] / 16 + 0.5
        if 0 <= lx < 64 and 0 <= ly < 64: self.send(gline(7, gchar(int(lx * 2)) + gchar(int(ly * 2)) + gchar(self.me.get("SPRITE", 2) & 3) + name.encode("latin1")))
        self._no_mount = self.clock() + 1.5; self.me["HORSEIMAGE"] = ""; self.send(gline(2, gchar(21) + gstr(b"")))
        self._set_move_gani(); return True   # off the horse: idle, not a riding pose without a horse

    def _set_move_gani(self):
        """After getting on or off a horse: the standing gani for the new state (ridestill or idle), also for the others."""
        n = self.move_gani("idle"); self.me["GANI"] = n; self.send(gline(2, gchar(PROP_GANI) + gstr(n.encode())))

    def hurt_by_server(self, dx, dy, power):
        """PLO_HURTPLAYER: damage (`power` hearts), a knock-back of (dx, dy) px when the way is free, the hurt gani; the server is told the new hearts."""
        self.me["HALFHEARTS"] = max(0, int(self.me.get("HALFHEARTS", 6) or 0) - power * 2); self.send_hearts(); self.play_gani("hurt", [])
        nx, ny = max(0, min(1008, self.pos[0] + dx)), max(0, min(1008, self.pos[1] + dy))
        if not self.coll.blocked(self, nx, ny): self.pos = (nx, ny)
        self.hurt_log = getattr(self, "hurt_log", []) + [(dx, dy, power)]

    def set_flag(self, name, on=True):
        """GS1 `set` / `unset`: the flag changes here and, online, PLI_FLAGSET (18) / PLI_FLAGDEL (19) tells the server (it keeps them in the account)."""
        name = name.strip()
        if on: self.flags.add(name)
        else: self.flags.discard(name); self.flag_values.pop(name, None)
        if not getattr(self, "local_inventory", False) and name: self.send(gline(18 if on else 19, name.encode("latin1", "replace")))

    def hit_npcs(self, event, near):
        """Fire a hit event (`washit`, `wasexploded`, `wasshot`) on every NPC that has it and whose shape (or touch box) satisfies `near(rect)`."""
        n = 0
        for nid, inst in list(self.npcrt.inst.items()):
            if not inst.has(event): continue
            rects = self.coll.npc_rects_of(self, nid)
            if not rects:
                gx, gy = self.npcrt._gpos(inst); w, h = self.npcrt._size(inst); rects = [(gx, gy, w, h)]
            if any(near(r) for r in rects): self.npcrt.run(inst, event); n += 1
        return n

    carrying = None
    show_stats = 0; show_local = False; no_pk = False; hud_hidden = False
    attached = None
    weapons_enabled = True

    def lift(self):
        """Pick up the carriable NPC (`canbecarried`) in front of the player; needs a glove (GLOVEPOWER >= 1). The NPC stops blocking and rides above the head."""
        if self.carrying is not None or float(self.me.get("GLOVEPOWER", 0) or 0) < 1: return False
        sr = self.sword_rect()
        for nid, inst in self.npcrt.inst.items():
            if not inst.fx.carriable or inst.fx.carried: continue
            rects = self.coll.npc_rects_of(self, nid)
            if any(sr[0] < q[0] + q[2] and sr[0] + sr[2] > q[0] and sr[1] < q[1] + q[3] and sr[1] + sr[3] > q[1] for q in rects):
                inst.fx.carried = True; self.carrying = nid; self.npcrt.version += 1; self._carry_tick()
                if isinstance(nid, int) and not self.gmap: self.send(gline(2, gchar(24) + gint_enc(nid, 3)))
                return True
        return False

    def _carry_tick(self):
        nid = self.carrying
        if nid is None: return
        inst = self.npcrt.inst.get(nid)
        if inst is None: self.carrying = None; return
        gx, gy = self._gpos(); icx, icy = inst.cell if self.gmap else (0, 0)
        inst.fx.x = (gx + 8 - icx * 1024) / 16; inst.fx.y = (gy - 20 - icy * 1024) / 16

    def throw(self):
        """Throw the carried NPC 3 tiles ahead (nearer if that is a wall) and fire its `wasthrown` event."""
        nid = self.carrying
        if nid is None: return False
        inst = self.npcrt.inst.get(nid)
        self.carrying = None
        if inst is None: return False
        gx, gy = self._gpos(); d = self.me.get("SPRITE", 2) & 3; dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[d]; icx, icy = inst.cell if self.gmap else (0, 0)
        for dist in (48, 32, 16, 0):
            inst.fx.x = (gx + dx * dist - icx * 1024) / 16; inst.fx.y = (gy + 24 + dy * dist - icy * 1024) / 16
            inst.fx.carried = False; self.npcrt.version += 1
            if dist == 0 or not self.coll.npc_rects_of(self, nid) or not any(self._blocked_g(q[0], q[1]) for q in self.coll.npc_rects_of(self, nid)): break
        if isinstance(nid, int):
            self.send(gline(11, b""))
            if not self.gmap: self.send(gline(2, gchar(24) + gint_enc(0, 3)))
            self.send_npc_pos(nid)
        if inst.has("wasthrown"): self.npcrt.run(inst, "wasthrown")
        return True

    def sword_rect(self):
        """The area the sword reaches (global px): a 32 x 32 box in front of the player's body."""
        gx, gy = self._gpos(); d = self.me.get("SPRITE", 2) & 3; dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[d]
        return (gx + 24 + dx * 28 - 16, gy + 40 + dy * 28 - 16, 32, 32)

    def blast_hits(self, cx, cy, radius_tiles):
        r = radius_tiles * 16
        def near(q):
            dx = max(q[0] - cx, 0, cx - (q[0] + q[2])); dy = max(q[1] - cy, 0, cy - (q[1] + q[3])); return dx * dx + dy * dy <= r * r
        return self.hit_npcs("wasexploded", near)

    def attacking(self): return time.time() < self.attack_until

    def stop(self):
        if time.time() < self.weapon_ani_until or self.holding_pose(): return
        n = self.move_gani("idle"); self.me["GANI"] = n; self.send(gline(2, gchar(PROP_GANI) + gstr(n.encode())))


    BUSH_TILES = (0x002, 0x003, 0x012, 0x013)
    CUT_TILES = (0x2A5, 0x2A6, 0x2B5, 0x2B6)

    def _apply_board(self, level, payload):
        if level is None: return
        x, y, w, h = (b - 0x20 for b in payload[:4]); tiles = [gint(payload[4 + 2 * i:6 + 2 * i]) for i in range(len(payload[4:]) // 2)]
        level.set_tiles(x, y, w, h, tiles)

    def _tile_here(self, tx, ty):
        """Tile index at tile (tx, ty) relative to our current sub-level (may lie in a loaded neighbour)."""
        lx, ly = tx // 64, ty // 64; name = self.level_name
        if (lx, ly) != (0, 0):
            rows = self.gmap_rows(); cx, cy = self.cell
            if not rows or not (0 <= cy + ly < len(rows) and 0 <= cx + lx < len(rows[0])): return None
            name = rows[cy + ly][cx + lx]
        lv = self.levels.get(name)
        return lv.tile(tx % 64, ty % 64) if lv and lv.board else None

    def find_bush(self):
        """Anchor (x, y) of a classic 2x2 bush right in front of the player's feet, in tiles of the current sub-level."""
        d = self.me.get("SPRITE", 2) & 3; dx, dy = ((0, -1), (-1, 0), (0, 1), (1, 0))[d]
        fx, fy = self.pos[0] + 24, self.pos[1] + 40
        for reach in (8, 20):
            tx, ty = int((fx + dx * reach) // 16), int((fy + dy * reach) // 16)
            t = self._tile_here(tx, ty)
            if t in self.BUSH_TILES:
                k = self.BUSH_TILES.index(t); ax, ay = tx - (k & 1), ty - (k >> 1)
                if all(self._tile_here(ax + i, ay + j) == self.BUSH_TILES[j * 2 + i] for j in range(2) for i in range(2)): return ax, ay
        return None

    def cut_bush(self, ax, ay):
        """PLI_BOARDMODIFY {x}{y}{w}{h}{GSHORT tiles}: replace the bush with the cut stump. The server drops items and respawns it."""
        if not (0 <= ax < 64 and 0 <= ay < 64): return False
        self.send(gline(1, gchar(ax) + gchar(ay) + gchar(2) + gchar(2) + b"".join(gint_enc(t, 2) for t in self.CUT_TILES)))
        lv = self.levels.get(self.level_name)
        if lv: lv.set_tiles(ax, ay, 2, 2, list(self.CUT_TILES))
        return True


    def pickup_items(self):
        """Walk over an item -> PLI_ITEMTAKE {GCHAR x/8}{GCHAR y/8}; the server removes it and sends the updated player props."""
        taken = []
        bx0, by0 = self.pos[0] + 12, self.pos[1] + 28
        for i in list(self.items):
            if i["cell"] != self.cell or i["level"] != self.level_name: continue
            if bx0 < i["x"] + 16 and bx0 + 24 > i["x"] and by0 < i["y"] + 16 and by0 + 24 > i["y"]:
                self.send(gline(32, gchar(i["x"] // 8) + gchar(i["y"] // 8)))
                self.items.remove(i); taken.append(i)
                if getattr(self, "local_inventory", False):
                    for prop, vals in self.ITEM_VALUE.items():
                        if i["type"] in vals: self.me[prop] = max(self.me.get(prop, 0), vals[i["type"]]) if prop == "GLOVEPOWER" else self.me.get(prop, 0) + vals[i["type"]]
        return taken


    RIDE_ANI = {"walk": "ride", "idle": "ridestill", "sword": "ridesword", "hurt": "ridehurt"}   # on a horse (HORSEIMAGE): the ride ganis draw horse and rider

    def resolve_ani(self, name):
        if self.me.get("HORSEIMAGE") and name in self.RIDE_ANI: name = self.RIDE_ANI[name]
        return self.ani_replace.get(name, name)

    def in_water(self, px=None, py=None):
        """Are the player's feet on a water tile (types 11 / 12)? Then the avatar swims."""
        px, py = (px, py) if px is not None else self.pos; cx, cy = self.cell if self.gmap else (0, 0)
        return self.coll.tile_type(self, (cx * 1024 + px + 24) // 16, (cy * 1024 + py + 40) // 16) in (11, 12)

    def move_gani(self, kind, px=None, py=None):
        """The gani for standing ("idle") or walking ("walk"): `swim` in water (the real client does that), else the (replaced) default."""
        if self.me.get("HORSEIMAGE"): return self.resolve_ani(kind)   # a horse does not swim
        return "swim" if self.in_water(px, py) and ganimod.load("swim") is not None else self.resolve_ani(kind)

    def play_gani(self, name, params=()):
        """GS1 setani: play gani `name` (after replaceani) on the player. The server stores the gani prop as `name[,param,...]`."""
        name = self.resolve_ani(name or "idle"); full = name + ("," + ",".join(params) if params else "")
        now = time.time(); self.weapon_ani_until = now + 0.3
        g = ganimod.load(name); busy = self.me.get("GANI") == full and (g is None or now - self.gani_start < max(ganimod.duration(g), 0.05) or g.loop or g.continuous)
        if busy: return
        self.me["GANI"] = full; self.gani_start = now
        self.send(gline(2, gchar(PROP_GANI) + gstr(full.encode("latin1"))))

    death_rng = random.Random()
    DEATH_GRALATS = (1, 50)

    def drop_on_death(self):
        """What gs2emu's `dropItemsOnDeath` does: lose 1..50 rupees (not more than we have) and 0..3 packs of 5 arrows / bombs; they land on the ground around
        the body (rupees as gold / red / blue / green, greedy), picked up again like any ground item for 8.2 s."""
        r = self.death_rng; have = int(self.me.get("GRALATS", 0) or 0); lost = min(r.randint(*self.DEATH_GRALATS), have)
        arrows = min(r.randint(0, 3), int(self.me.get("ARROWS", 0) or 0) // 5); bombs = min(r.randint(0, 3), int(self.me.get("BOMBS", 0) or 0) // 5)
        self.me["GRALATS"] = have - lost; self.me["ARROWS"] = int(self.me.get("ARROWS", 0) or 0) - arrows * 5; self.me["BOMBS"] = int(self.me.get("BOMBS", 0) or 0) - bombs * 5
        types = []; left = lost
        for typ, val in ((19, 100), (2, 30), (1, 5), (0, 1)):
            while left >= val: types += [typ]; left -= val
        types += [4] * arrows + [3] * bombs
        cell = self.cell if self.gmap else (0, 0); now = time.time()
        for typ in types[:40]:
            x = max(0, min(1008, self.pos[0] + 16 + r.randint(-4, 4) * 16)); y = max(0, min(1008, self.pos[1] + 32 + r.randint(-4, 4) * 16))
            self.items.append(dict(x=x // 8 * 8, y=y // 8 * 8, type=typ, cell=cell, level=self.level_name, t0=now))
        return dict(rupees=lost, arrows=arrows * 5, bombs=bombs * 5)

    PLSTATUS_DEAD = 0x08

    def set_status(self, dead):
        """Set / clear the DEAD bit of the STATUS prop (18) and tell the server (gs2emu reacts to the change: deaths, drops, hearts on revival)."""
        st = int(self.me.get("STATUS", 0) or 0); st = (st | self.PLSTATUS_DEAD) if dead else (st & ~self.PLSTATUS_DEAD); self.me["STATUS"] = st
        self.send(gline(2, gchar(18) + gchar(st)))

    def send_hearts(self):
        """Tell the server our hearts changed (a client script hurt us: `playerhearts -= .5`, `hurt n`); offline there is nobody to tell."""
        if not getattr(self, "local_inventory", False): self.send(gline(2, gchar(2) + gchar(max(0, min(255, int(self.me.get("HALFHEARTS", 0) or 0))))))

    DEATH_SECS = 3.0
    dead_until = None; _spawn = None

    def death_tick(self):
        """0 hearts (the prop is present and has dropped to 0 after being above): play `dead`, freeze, fire `playerdies`; after DEATH_SECS a local inventory
        (offline) respawns with full hearts at the place where the session started, online the server decides (we only stop the animation when hearts are back)."""
        hh = self.me.get("HALFHEARTS"); now = self.clock()
        if hh is None: return
        if self._spawn is None: self._spawn = (self.cell, self.pos)
        if self.dead_until is None:
            if hh <= 0 and getattr(self, "_alive_seen", False):
                self.dead_until = now + self.DEATH_SECS; self.weapon_ani_until = 0.0; self.play_gani("dead", [])
                self.freeze(self.DEATH_SECS); self.runner.broadcast("playerdies"); self.npcrt.broadcast("playerdies")
                self.deaths = getattr(self, "deaths", 0) + 1
                if getattr(self, "local_inventory", False): self.drop_on_death()
                else: self.set_status(dead=True)
            elif hh > 0: self._alive_seen = True
        elif now >= self.dead_until:
            if not getattr(self, "local_inventory", False) and hh <= 0:
                if not getattr(self, "_revive_sent", None): self.set_status(dead=False); self._revive_sent = now
                elif now - self._revive_sent > 5.0: self._revive_sent = None; self.dead_until = None
                return
            if hh > 0 or getattr(self, "local_inventory", False):
                self._revive_sent = None
                if hh <= 0: self.me["HALFHEARTS"] = max(2, int(self.me.get("FULLHEARTS", 3) or 3) * 2)
                if self.local_inventory and self._spawn: (cx, cy), pos = self._spawn; self.teleport(pos[0] / 16, pos[1] / 16, (cx, cy) if self.gmap else None, check=False)
                self.dead_until = None; self.frozen_until = 0.0; self.me["GANI"] = "idle"; self.stop()

    def freeze(self, seconds): self.frozen_until = max(self.frozen_until, time.time() + seconds)
    server_frozen = False; is_leader = False; local_inventory = False
    def frozen(self): return self.server_frozen or time.time() < self.frozen_until

    def load_map(self, name):
        """GS1 loadmap <gmap>: online the server announces the gmap itself (PLAYERWARP2), so this only records the request."""
        self.loaded_map = name

    def onwall(self, x, y, level=None):
        """GS1 onwall(x,y): is the tile at level-local tile (x,y) a wall (tile types 20/21/22)? Outside the level counts as a wall."""
        lv = self.levels.get(level or self.level_name); tx, ty = int(x // 1), int(y // 1)
        if not (0 <= tx < 64 and 0 <= ty < 64): return True
        if not lv or not lv.board: return False
        return self.tile_table(level or self.level_name)[lv.tile(tx, ty) & 0xFFF] in collision.BLOCKING

    def play_sound(self, name, loop=False, from_weapon=False):
        """GS1 play / playlooped: the viewer installs a device-backed Audio; headless sessions just record the request.
        A looped sound from a level NPC belongs to that level (or gmap): it stops when the player leaves it (_enter_world). A weapon's goes on."""
        if getattr(self, "audio", None) is None:
            import audio; self.audio = audio.Audio(device=False)
        if loop: self._loop_from_level = not from_weapon
        return self.audio.play(name, loop)

    def stop_sound(self, name=None):
        if getattr(self, "audio", None): self.audio.stop(name)

    def set_focus(self, x, y, cell=None):
        """GS1 setfocus x,y: the camera centres on level tile (x,y) instead of the player; resetfocus goes back."""
        cx, cy = cell if cell is not None else (self.cell if self.gmap else (0, 0)); self.focus = (cx * 1024 + x * 16, cy * 1024 + y * 16)

    def set_player_prop(self, key, text):
        """setplayerprop #c,text = chat bubble; #P1..#P3 = gani attributes (hat etc., props 37..39)."""
        if key == "#c": self.say(text); return
        m = re.fullmatch(r"#P(\d)", key)
        if m and 1 <= int(m.group(1)) <= 5:
            self.send(gline(2, gchar(36 + int(m.group(1))) + gstr(text.encode("latin1")))); self.me[f"GATTRIB{m.group(1)}"] = text

    def update_gani(self):
        """Non-looping ganis end by themselves: go back to SETBACKTO (default idle)."""
        base = (self.me.get("GANI") or "idle").split(",")[0]
        # the standing / walking ganis (also on a horse: ridestill / ride) are not one-shot ganis to end: treated as idle, ridestill was
        # restarted again and again, and each restart held the gani for 0.3 s, so walking never showed "ride" (horse and rider slid along standing)
        if base in ("idle", "walk", "swim", self.resolve_ani("idle"), self.resolve_ani("walk")) or self.attacking() or self.holding_pose(): return
        g = ganimod.load(base)
        if g is None or g.loop or g.continuous: return
        if time.time() - self.gani_start >= ganimod.duration(g) and time.time() >= self.weapon_ani_until:
            self.play_gani(g.setbackto or "idle")


    # ---- guilds: membership and ranks live on the server (guilds/guild<Name>.txt, ranks as "#leader Account" / "#officer Account" lines);
    # the gr.guild trigger commands of the patched gs2emu check every change. The client only shows them and asks.
    GUILD_RANKS = ("member", "officer", "leader")

    def guild_cmd(self, *args):
        """Ask the server: guild_cmd("info"), ("add", guild, account), ("remove", guild, account), ("leave", guild), ("rank", guild, account, "officer")."""
        self.send_triggeraction(0, 0, 0, ["gr.guild"] + [str(a) for a in args])

    def _guild_reply(self, fields):
        """clientside,-Guilds,info,<n>,{name,myrank,count,{account,rank,nickname}...}... or clientside,-Guilds,message,<text>.
        nickname: the one name the account may wear with the tag ("" = any name)."""
        kind = fields[0].lower() if fields else ""
        if kind == "message" and len(fields) > 1: self.guild_message = (fields[1], time.time())
        elif kind == "info":
            out, i = [], 2
            try:
                for _ in range(int(fields[1])):
                    name, rank, n = fields[i], int(fields[i + 1]), int(fields[i + 2]); i += 3
                    members = [(fields[i + 3 * k], int(fields[i + 3 * k + 1]), fields[i + 3 * k + 2]) for k in range(n)]; i += 3 * n
                    out.append(dict(name=name, rank=rank, members=sorted(members, key=lambda m: (-m[1], m[0].lower()))))
            except (IndexError, ValueError): pass   # keep what was read
            self.guilds = out

    @property
    def guild(self):
        """The guild tag of our nickname, but only when the server lists us in that guild (#g in scripts, so a gate opens only for real members)."""
        forced = self.__dict__.get("_guild_forced")
        if forced is not None: return forced   # offline play and tests set it directly (no server to ask)
        nick = str(self.me.get("NICKNAME") or "")
        m = re.search(r"\(([^()]*)\)\s*$", nick)
        if not m: return ""
        tag = m.group(1).strip()
        return tag if any(g["name"].lower() == tag.lower() for g in getattr(self, "guilds", ())) else ""

    @guild.setter
    def guild(self, value): self._guild_forced = value

    def nick_base(self):
        """Our nickname without the (guild) tag."""
        return re.sub(r"\s*\([^()]*\)\s*$", "", str(self.me.get("NICKNAME") or "")).strip() or str(getattr(self, "account_name", "") or "unknown")

    def guild_name_for(self, guild_name):
        """The name the guild gave our account ("Sir Patrick Graham, Knight of"), or "" when any name may wear its tag."""
        me = str(getattr(self, "account_name", "") or "").lower()
        for g in getattr(self, "guilds", ()):
            if g["name"].lower() == guild_name.lower():
                for m in g["members"]:
                    if m[0].lower() == me: return m[2] if len(m) > 2 else ""
        return ""

    def set_guild_tag(self, guild_name):
        """Wear the tag of a guild (or none with ""): the server's own setnick chat command, which checks the guild file and answers with the nickname.
        A guild that gave our account a name gets that name with the tag (the server allows no other)."""
        nick = (self.guild_name_for(guild_name) or self.nick_base()) + (f" ({guild_name})" if guild_name else "")
        self.send(gline(2, gchar(12) + gstr(("setnick " + nick).encode("latin1", "replace")[:223])))   # not shown as our chat bubble
        self.guild_message = ("Asked for: " + nick, time.time())

    def send_triggeraction(self, npc_id, x, y, items):
        """PLI_TRIGGERACTION (38): {GINT3 npc}{GCHAR x*2}{GCHAR y*2}{CSV action,param,...}; the server routes it (NPC-server events, gr.* hacks)."""
        self.send(gline(38, gint_enc(int(npc_id), 3) + gchar(max(0, int(x * 2))) + gchar(max(0, int(y * 2))) + csv_join(items).encode("latin1")))
    COLOR_NAMES = ("white yellow orange pink red darkred lightgreen green darkgreen lightblue blue darkblue brown cynober purple darkpurple "
                   "lightgray gray black transparent").split()

    def say2(self, text):
        """say2: sign / message window. `#b` = line break; `#i(img)` inline images are dropped."""
        text = re.sub(r"#i\([^)]*\)", "", text).replace("#b", "\n").strip(); self.sign = (text, time.time() + 6.0)
        mb = getattr(self, "msgbox", None)
        if mb is None or mb.text != text or mb.expired(): from messagebox import MessageBox; self.msgbox = MessageBox(text)

    def show_text(self, idx, x, y, text): self.texts[idx] = dict(x=x, y=y, text=text)
    def hide_text(self, idx): self.texts.pop(idx, None)

    def show_poly(self, pid, pts): self.polys[pid] = pts
    def hide_poly(self, pid): self.polys.pop(pid, None)

    def wrap_text(self, width, text, char_px=6.5):
        """GS1 wraptext2 width,flags,,@font@text: split into lines that fit `width` px (a font-less estimate) and keep them as the tokens #t(n)."""
        text = re.sub(r"^\s*@[^@]*@", "", text); cap = max(1, int(width / char_px)); lines, cur = [], ""
        for word in text.split():
            if cur and len(cur) + 1 + len(word) > cap: lines.append(cur); cur = word
            else: cur = (cur + " " + word).strip()
        if cur: lines.append(cur)
        self.tokens = lines

    def set_color(self, slot, name):
        """setskincolor/setcoatcolor/setsleevecolor/setshoecolor/setbeltcolor: update COLORS (prop 13, five colour indices)."""
        n = name.strip().lower()
        if n not in self.COLOR_NAMES: return
        cols = list(self.me.get("COLORS") or [0, 0, 0, 0, 0])[:5]; cols += [0] * (5 - len(cols)); cols[slot] = self.COLOR_NAMES.index(n)
        self.me["COLORS"] = cols; self.send(gline(2, gchar(13) + bytes(32 + c for c in cols)))

    def show_img(self, idx, image, x, y): self.imgs[idx] = dict(image=image, x=x, y=y, vis=None, color=None, zoom=1.0, part=None)
    def img_prop(self, idx, **kw):
        if idx in self.imgs: self.imgs[idx].update(kw)
    def hide_imgs(self, lo, hi=None):
        for k in [k for k in self.imgs if (lo <= k <= (hi if hi is not None else lo))]: del self.imgs[k]

def csv_join(items):
    """Server side uses string::fromCSV: quote fields that contain a comma or a double quote."""
    out = []
    for it in items:
        it = str(it)
        out.append('"' + it.replace('"', '""') + '"' if ("," in it or '"' in it) else it)
    return ",".join(out)

def csv_split(text):
    out, cur, q, i = [], "", False, 0
    while i < len(text):
        c = text[i]
        if q:
            if c == '"' and text[i + 1:i + 2] == '"': cur += '"'; i += 1
            elif c == '"': q = False
            else: cur += c
        elif c == '"': q = True
        elif c == ",": out.append(cur.strip()); cur = ""
        else: cur += c
        i += 1
    out.append(cur.strip())
    return out

