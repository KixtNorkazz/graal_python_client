"""Projectiles (`shoot x,y,z,angle,zangle,power,gani,params`, `setshootparams`; PLI_SHOOT 40 / PLO_SHOOT 175).
Physics copied from gs2emu (LevelShoot.h / Level::moveShoot), in tiles, one step per 0.05 s:
  power > 0: speed = power/44 tiles per step (cos(zangle) horizontal, sin(zangle) vertical), vz -= gravity*0.05 each step
  power <= 0 (old projectile): no gravity, 1 tile per step
  x += cos(angle)*h, y -= sin(angle)*h, z += vz;  landing = z <= 0 while falling, or a wall while z <= 3 and falling/level.
Landing from our own shot fires `actionprojectile2` (params: x, y, shootparams...) on the client weapons.
Positions are kept in gmap-global tiles (cell*64 + local), so one list works across sub-levels."""
import math, time
from graalproto import gline, gchar, gstr, gint_enc

STEP = 0.05
MAX_AGE = 12.0
TWO_PI = 2 * math.pi

class Projectile:
    def __init__(self, gx, gy, z, angle, zangle, power, gani, params, gravity=2.0, local=True):
        self.x, self.y, self.z = gx, gy, z; self.gani, self.params, self.local = gani, list(params), local
        self.gravity = gravity if power > 0 else 0.0
        sp = (power / 44.0) if power > 0 else 1.0
        h = math.cos(zangle) * sp if power > 0 else sp
        self.vx, self.vy = math.cos(angle) * h, math.sin(angle) * h
        self.vz = math.sin(zangle) * sp if power > 0 else 0.0
        self.t0 = time.time(); self.next = self.t0 + STEP

class Projectiles:
    def __init__(self, session): self.s = session; self.list = []; self.shootparams = []; self.landed = []

    def _origin(self):
        s = self.s; cx, cy = s.cell if s.gmap else (0, 0); return cx * 64, cy * 64

    def shoot(self, x, y, z, angle, zangle, power, gani, params):
        """Local shot (tile coords relative to the current level) + PLI_SHOOT to the server."""
        s = self.s; params = list(params) or list(self.shootparams); gani = (gani or "").rstrip(",")
        ox, oy = self._origin(); self.list.append(Projectile(ox + x, oy + y, z, angle % TWO_PI, zangle, power, gani, params))
        sang = int(round((angle % TWO_PI) / TWO_PI * 220)) % 221
        szang = max(0, min(220, int(round((zangle / (math.pi / 2) + 1) * 110))))
        pw = max(0, min(220, int(power * 44)))
        csv = ",".join(params).encode("latin1", "replace")
        s.send(gline(40, gint_enc(0, 3) + gchar(int(x * 2)) + gchar(int(y * 2)) + gchar(int(z) + 50) + gchar(sang) + gchar(szang)
                         + gchar(pw) + gstr(gani.encode("latin1", "replace")) + gchar(len(csv[:223])) + csv[:223]))

    def remote_arrow(self, x, y, d, from_player=True):
        """PLO_ARROWADD: another player's arrow (flies one tile per step in direction d = 0 up, 1 left, 2 down, 3 right); it can hit NPCs here (`wasshot`)."""
        ox, oy = self._origin(); ang = (math.pi / 2, math.pi, 1.5 * math.pi, 0.0)[d & 3]
        p = Projectile(ox + x, oy + y, 0.5, ang, 0.0, 0, "arrow", [], local=False); p.hits = from_player; self.list.append(p)

    def remote(self, payload):
        """PLO_SHOOT 175 {GINT source}{x/8}{y/8}{z+50}{angle}{zangle}{power}{gani}{params}: another player's shot (visual only)."""
        try:
            o = 5
            b = lambda k: payload[o + k] - 0x20
            x, y, z = b(0) * 8 / 16, b(1) * 8 / 16, b(2) - 50
            ang, zang, pw = b(3) / 220 * TWO_PI, (b(4) / 110 - 1) * math.pi / 2, b(5)
            n = b(6); gani = payload[o + 7:o + 7 + n].decode("latin1"); pn = b(7 + n)
            params = payload[o + 8 + n:o + 8 + n + pn].decode("latin1").split(",") if pn else []
        except (IndexError, ValueError): return
        ox, oy = self._origin(); self.list.append(Projectile(ox + x, oy + y, z, ang, zang, pw, gani.rstrip(","), params, local=False))

    def tick(self, now=None):
        s = self.s; now = now or time.time(); keep = []
        for p in self.list:
            alive = now - p.t0 < MAX_AGE
            while alive and p.next <= now:
                p.next += STEP; p.vz -= p.gravity * STEP; p.x += p.vx; p.y -= p.vy; p.z += p.vz
                if self._hit(p): alive = False; self._land(p)
            if alive: keep.append(p)
        self.list = keep

    def _hit(self, p):
        s = self.s; gx, gy = int(p.x // 1), int(p.y // 1)
        if (p.local or getattr(p, "hits", False)) and p.z <= 3:
            px, py = p.x * 16, p.y * 16
            if s.hit_npcs("wasshot", lambda q: q[0] <= px < q[0] + q[2] and q[1] <= py < q[1] + q[3]): return True
        if not s.gmap and not (0 <= gx < 64 and 0 <= gy < 64): return True
        if s.gmap:
            rows = s.gmap_rows()
            if rows and not (0 <= gx < 64 * len(rows[0]) and 0 <= gy < 64 * len(rows)): return True
        if p.z <= 0 and p.vz <= 0 and p.gravity > 0: return True
        if p.z <= 3 and p.vz <= 0:
            rows = s.gmap_rows() if s.gmap else None
            if s.coll.tile_blocked(s, gx, gy, rows): return True
        return False

    def _land(self, p):
        if not p.local: return
        ox, oy = self._origin(); lx, ly = p.x - ox, p.y - oy
        self.landed.append((lx, ly, p.gani))
        self.s.runner.broadcast("actionprojectile2", params=[f"{lx:g}", f"{ly:g}"] + p.params)

    def view(self, now=None):
        now = now or time.time()
        return [dict(gani=p.gani, gx=p.x * 16, gy=p.y * 16, z=p.z, age=now - p.t0, params=p.params) for p in self.list]
