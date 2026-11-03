"""Client-side collision: tile types (gs2emu tables) of the loaded sub-levels plus NPC shapes from `setshape`/`setshape2`.
Player blocking box = 16x16 px at (x+16, y+32), the player's feet (gs2emu uses the same reference point x+1.5, y+2 tiles)."""
import gs1
from tiletypes import TYPE0

BLOCKING = (20, 21, 22)
BOX = (16, 32, 16, 16)

class Collision:
    def __init__(self): self._key = None; self._rects = []; self._ids = []; self._grid = {}; self._by_id = {}

    def _npc_rects(self, s):
        """Blocking rectangles of NPCs in gmap-global px (cell*1024 + local)."""
        key = (len(s.npcs), s.level_name, s.gmap, s.npcrt.version)
        if key == self._key: return self._rects
        rects = []; ids = []
        for nid, n in s.npcs.items():
            if "X2" not in n: continue
            fx = s.npcrt.fx(nid, n)
            if fx.noblock or fx.carried or not fx.shape or nid == s.attached: continue
            cx, cy = (n.get("GMAPLEVELX", 0), n.get("GMAPLEVELY", 0)) if s.gmap else (0, 0)
            x0 = cx * 1024 + int(fx.x * 16); y0 = cy * 1024 + int(fx.y * 16)
            if fx.shape[0] == "rect": rects.append((x0, y0, fx.shape[1], fx.shape[2])); ids.append(nid)
            else:
                _, w, h, types = fx.shape
                for i, t in enumerate(types):
                    if t in BLOCKING: rects.append((x0 + (i % w) * 16, y0 + (i // w) * 16, 16, 16)); ids.append(nid)
        self._key, self._rects, self._ids = key, rects, ids
        grid = {}; by_id = {}
        for k, (rx, ry, rw, rh) in enumerate(rects):
            by_id.setdefault(ids[k], []).append(rects[k])
            for gx in range(rx // 64, (rx + rw - 1) // 64 + 1):
                for gy in range(ry // 64, (ry + rh - 1) // 64 + 1): grid.setdefault((gx, gy), []).append(k)
        self._grid, self._by_id = grid, by_id
        return rects

    def _near(self, x0, y0, x1, y1):
        """Indices of the NPC rectangles in the buckets that the box (x0, y0, x1, y1) touches (a superset of the overlapping ones), in index order."""
        grid = self._grid; out = set()
        for gx in range(x0 // 64, (x1 - 1) // 64 + 1):
            for gy in range(y0 // 64, (y1 - 1) // 64 + 1):
                b = grid.get((gx, gy))
                if b: out.update(b)
        return sorted(out)

    def npc_rects_of(self, s, nid):
        """The blocking rectangles (gmap-global px, at the NPC's current position) of one NPC."""
        self._npc_rects(s); return list(self._by_id.get(nid, ()))

    def wall_overlap(self, s, px, py):
        """How many pixels of the player's box at local (px, py) lie on wall tiles (0 = none). Used to let a player who was put inside a wall
        (a warp or link whose destination overlaps one) walk out of it: a step is allowed when it lowers this, never deeper or along it."""
        rows = s.gmap_rows() if s.gmap else None
        cx, cy = s.cell if s.gmap else (0, 0)
        x0 = cx * 1024 + px + BOX[0]; y0 = cy * 1024 + py + BOX[1]; x1 = x0 + BOX[2]; y1 = y0 + BOX[3]; area = 0
        for gty in range(y0 // 16, (y1 - 1) // 16 + 1):
            for gtx in range(x0 // 16, (x1 - 1) // 16 + 1):
                if self.tile_blocked(s, gtx, gty, rows):
                    area += (min(x1, gtx * 16 + 16) - max(x0, gtx * 16)) * (min(y1, gty * 16 + 16) - max(y0, gty * 16))
        return area

    def blockers(self, s, px, py):
        """Ids of the NPCs whose shapes the player's box at local (px, py) overlaps."""
        cx, cy = s.cell if s.gmap else (0, 0)
        x0 = cx * 1024 + px + BOX[0]; y0 = cy * 1024 + py + BOX[1]; x1 = x0 + BOX[2]; y1 = y0 + BOX[3]; out = []
        rects = self._npc_rects(s)
        for k in self._near(x0, y0, x1, y1):
            rx, ry, rw, rh = rects[k]; nid = self._ids[k]
            if x0 < rx + rw and x1 > rx and y0 < ry + rh and y1 > ry and nid not in out: out.append(nid)
        return out

    def rect_blocked(self, s, rect, ignore=()):
        """Would a rectangle (gmap-global px) overlap a wall tile or the shape of an NPC that is not in `ignore`?"""
        rows = s.gmap_rows() if s.gmap else None; x0, y0, w, h = rect
        for gty in range(int(y0) // 16, (int(y0 + h) - 1) // 16 + 1):
            for gtx in range(int(x0) // 16, (int(x0 + w) - 1) // 16 + 1):
                if self.tile_blocked(s, gtx, gty, rows): return True
        rects = self._npc_rects(s)
        for k in self._near(int(x0), int(y0), int(x0 + w), int(y0 + h)):
            rx, ry, rw, rh = rects[k]
            if self._ids[k] not in ignore and x0 < rx + rw and x0 + w > rx and y0 < ry + rh and y0 + h > ry: return True
        return False

    def tile_type(self, s, gtx, gty):
        """Tile type (0 walkable, 11/12 water, ...) of global tile (gtx, gty), or None when that level is not loaded."""
        rows = s.gmap_rows() if s.gmap else None; lx, ly = gtx // 64, gty // 64
        if rows:
            if not (0 <= ly < len(rows) and 0 <= lx < len(rows[0])): return None
            lv = s.levels.get(rows[ly][lx])
        else:
            if (lx, ly) != (0, 0): return None
            lv = s.levels.get(s.level_name)
        if not lv or not lv.board: return None
        return TYPE0[lv.tile(gtx % 64, gty % 64) & 0xFFF]

    def tile_blocked(self, s, gtx, gty, rows):
        """Is global tile (gtx, gty) a wall? Unknown (unloaded) gmap levels count as free, outside a single level as blocked."""
        lx, ly = gtx // 64, gty // 64
        if rows:
            if not (0 <= ly < len(rows) and 0 <= lx < len(rows[0])): return True
            lv = s.levels.get(rows[ly][lx])
            if not lv or not lv.board: return False
        else:
            if (lx, ly) != (0, 0):
                for name, ox, oy in s.adjacent_levels():
                    nl = s.levels.get(name); tx, ty = gtx - int(ox), gty - int(oy)
                    if nl and nl.board and 0 <= tx < 64 and 0 <= ty < 64: return TYPE0[nl.tile(tx, ty) & 0xFFF] in BLOCKING
                return True
            lv = s.levels.get(s.level_name)
            if not lv or not lv.board: return False
        return TYPE0[lv.tile(gtx % 64, gty % 64) & 0xFFF] in BLOCKING

    def blocked(self, s, px, py, skip=None):
        """True if the player's blocking box at local position (px, py) overlaps a wall tile or an NPC shape (`skip`: ids of NPCs to ignore,
        used for path planning around NPCs that are moving: they are priced where they will be instead)."""
        rows = s.gmap_rows() if s.gmap else None
        cx, cy = s.cell if s.gmap else (0, 0)
        x0 = cx * 1024 + px + BOX[0]; y0 = cy * 1024 + py + BOX[1]; x1 = x0 + BOX[2]; y1 = y0 + BOX[3]
        for gty in range(y0 // 16, (y1 - 1) // 16 + 1):
            for gtx in range(x0 // 16, (x1 - 1) // 16 + 1):
                if self.tile_blocked(s, gtx, gty, rows): return True
        rects = self._npc_rects(s)
        for k in self._near(x0, y0, x1, y1):
            if skip and self._ids[k] in skip: continue
            rx, ry, rw, rh = rects[k]
            if x0 < rx + rw and x1 > rx and y0 < ry + rh and y1 > ry: return True
        return False
