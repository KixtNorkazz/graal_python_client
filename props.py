"""Player / NPC property parsing for the gs2emu wire format (types from gs2emu PropertySerializers / NPC.h / PlayerProps.h)."""
from graalproto import gint, gint_enc
import enums

class Reader:
    def __init__(self, b): self.b, self.i = b, 0
    def left(self): return len(self.b) - self.i
    def byte(self): v = self.b[self.i] - 0x20; self.i += 1; return v
    def raw(self, n): v = self.b[self.i:self.i + n]; self.i += n; return v
    def num(self, n): return gint(self.raw(n))
    def gstr(self): return self.raw(self.byte()).decode("latin1")

def _sword_like(r, base=30, preset="sword"):
    p = r.byte()
    if p < base: return {"power": p, "image": f"{preset}{p}.png" if 0 < p <= 4 else ""}
    return {"power": p - base, "image": r.gstr()}

def _shield(r): return _sword_like(r, 10, "shield")

def _head(r):
    n = r.byte()
    return r.raw(n - 100).decode("latin1") if n >= 100 else f"head{n}.png"

def _px(r):
    v = r.num(2); return -(v >> 1) if v & 1 else v >> 1

def _colors(r, n=5): return [r.byte() for _ in range(n)]

def parse_npc(payload: bytes):
    """-> (npc_id, {name: value}); raises on structural mismatch so the parser can be validated on real traffic."""
    r = Reader(payload); npc_id = r.num(3); out = {}
    while r.left() > 0:
        pid = r.byte(); name = enums.NPCPROP.get(pid, f"P{pid}")
        if pid == 0: v = r.gstr()
        elif pid == 1: v = r.raw(r.num(2)).replace(b"\xa7", b"\n").decode("latin1")
        elif pid in (2, 3): v = r.byte() / 2
        elif pid in (4, 6, 7, 8, 9, 13, 14, 18, 33, 41, 42) or 23 <= pid <= 32: v = r.byte()
        elif pid == 5 or pid == 17: v = r.num(3)
        elif pid == 10: v = _sword_like(r)
        elif pid == 11: v = _shield(r)
        elif pid == 12: v = r.gstr()
        elif pid == 15 or pid == 20 or pid == 21 or pid == 35 or 36 <= pid <= 40 or 44 <= pid <= 47 or 49 <= pid <= 73: v = r.gstr()
        elif pid == 16: v = (r.byte(), r.byte())
        elif pid == 19: v = _colors(r) if r.b[r.i] != 0x20 else [r.byte()]
        elif pid == 22: v = _head(r)
        elif pid == 34: v = dict(x=r.num(2), y=r.num(2), w=r.byte(), h=r.byte())
        elif pid == 43: v = r.byte() - 50
        elif pid == 48: v = None
        elif pid == 74: v = r.raw(r.num(2)).decode("latin1")
        elif pid in (75, 76, 77): v = _px(r)
        else:
            e = ValueError(f"unknown NPC prop {pid} at {r.i} of {len(payload)}"); e.partial = out; raise e
        out[name] = v
    return npc_id, out

def parse_player(payload: bytes):
    """Parse a player prop list (own props, or after the id in OTHERPLPROPS). Returns {name: value}."""
    r = Reader(payload); out = {}
    while r.left() > 0:
        pid = r.byte(); name = enums.PLPROP.get(pid, f"P{pid}")
        if pid in (0, 10, 12, 20, 21, 34, 35, 52, 75) or 37 <= pid <= 41 or 46 <= pid <= 49 or 54 <= pid <= 74: v = r.gstr()
        elif pid in (1, 2, 4, 5, 6, 7, 15, 16, 17, 18, 19, 22, 26, 32, 33, 43, 44): v = r.byte()
        elif pid in (3, 24, 27, 28, 29, 31, 36, 76, 77): v = r.num(3)
        elif pid == 8: v = _sword_like(r)
        elif pid == 9: v = _shield(r)
        elif pid == 11: v = _head(r)
        elif pid == 13: v = _colors(r)
        elif pid in (14, 25): v = r.num(2)
        elif pid == 23:
            n = r.byte(); v = r.raw(max(0, n) * 1) if n else b""; 
        elif pid == 30: v = r.num(5)
        elif pid == 45: v = (r.byte() - 50)
        elif pid in (78, 79, 80): v = _px(r)
        elif pid == 81: v = r.byte()
        elif pid == 50: v = r.byte()
        elif pid == 51: v = None
        elif pid == 53: v = r.byte()
        elif pid == 82: v = r.gstr()
        elif pid == 83: v = r.num(5)
        else: out["_unknown_prop"] = pid; break
        out[name] = v
    return out
