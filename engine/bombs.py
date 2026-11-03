"""`putbomb type,x,y`: a bomb that explodes after 3 s (gs2emu: "It takes 3 seconds for a bomb to explode").
Sent as PLI_BOMBADD (4) {GUCHAR x*2}{GUCHAR y*2}{GUCHAR power}{GUCHAR 0.05 s ticks left}; the explosion as PLI_EXPLOSION (27)
{radius}{x*2}{y*2}{power}. The look (bomb sprite, expanding fire rings) is an approximation: the real client's explosion graphic is not known here."""
import time
from graalproto import gline, gchar

FUSE = 3.0
BLAST = 0.5

class Bomb:
    def __init__(self, gx, gy, power, local):
        self.gx, self.gy, self.power, self.local, self.send = gx, gy, power, local, True; self.t0 = time.time()

class Bombs:
    def __init__(self, session): self.s = session; self.bombs = []; self.blasts = []; self.log = []

    def remove(self, x, y):
        cx, cy = self.s.cell if self.s.gmap else (0, 0); self.bombs = [b for b in self.bombs if not (abs(b.gx - (cx * 64 + x)) < 0.5 and abs(b.gy - (cy * 64 + y)) < 0.5)]

    def put(self, x, y, kind=1, cell=None, send=True, remote=False):
        s = self.s; cx, cy = cell if cell is not None else (s.cell if s.gmap else (0, 0))
        power = max(0, min(3, int(kind)))
        if (len(self.bombs) >= 64 and not send) or any(abs(b.gx - (cx * 64 + x)) < 0.5 and abs(b.gy - (cy * 64 + y)) < 0.5 for b in self.bombs): return
        b = Bomb(cx * 64 + x, cy * 64 + y, power, not remote); b.remote = remote; b.send = send; self.bombs.append(b); self.log.append(("put", x, y, power))
        if send and 0 <= x < 64 and 0 <= y < 64: s.send(gline(4, gchar(int(x * 2)) + gchar(int(y * 2)) + gchar(power) + gchar(int(FUSE / 0.05) - 5)))

    def tick(self, now=None):
        s = self.s; now = now or time.time(); keep = []
        for b in self.bombs:
            if now - b.t0 >= FUSE:
                radius = 2 + b.power; self.blasts.append((b.gx, b.gy, now, radius)); self.log.append(("boom", b.gx, b.gy, radius))
                if not getattr(b, "remote", False): s.blast_hits(b.gx * 16, b.gy * 16, radius)
                cx, cy = (s.cell if s.gmap else (0, 0)); lx, ly = b.gx - cx * 64, b.gy - cy * 64
                if b.local and b.send and 0 <= lx < 64 and 0 <= ly < 64: s.send(gline(27, gchar(radius) + gchar(int(lx * 2)) + gchar(int(ly * 2)) + gchar(b.power)))
            else: keep.append(b)
        self.bombs = keep; self.blasts = [x for x in self.blasts if now - x[2] < BLAST]

    def view(self, now=None):
        now = now or time.time()
        return dict(bombs=[dict(gx=b.gx * 16, gy=b.gy * 16, age=now - b.t0) for b in self.bombs],
                    blasts=[dict(gx=x[0] * 16, gy=x[1] * 16, f=(now - x[2]) / BLAST, r=x[3]) for x in self.blasts])
