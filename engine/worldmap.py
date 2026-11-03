"""The map (M): every level of the current .gmap as a small picture, with the other players who are online on the same gmap.

Each level is one 64 x 64 picture (one pixel per tile, the average colour of the tile). The level files come from the local folders or are fetched from the
game server one by one while the map is open. Players are placed from what the server told us about them: the level they are in and their position in it."""
import hashlib, os, time
from PIL import Image, ImageDraw
import assets, nwlevel, render, window

LEVEL_PX = 64
NEAR = 1
LIVE_SECS = 12.0
PER_FRAME = 6
GMAP_BG = (14, 18, 22, 255)
UNKNOWN = (34, 40, 46, 255)


def player_color(name):
    h = hashlib.md5(name.encode("utf-8", "replace")).digest()
    return tuple(90 + h[i] % 166 for i in range(3))


class WorldMap:
    def __init__(self):
        self.open = False
        self.gmap = None
        self.thumbs = {}
        self._tile_color = {}
        self._base = None
        self._base_count = -1
        self.hover = None

    def toggle(self, s):
        self.open = not self.open
        if self.open and self.gmap != s.gmap: self.gmap, self.thumbs, self._base = s.gmap, {}, None

    def key(self, sym, s):
        if sym in (window.K_ESCAPE, ord("m")): self.open = False
        return True

    def _board(self, s, name):
        lv = s.levels.get(name)
        if lv is not None and lv.board: return lv.board
        path = assets.find(name, level=True)
        if not path: return None
        try: return nwlevel.load_nw(path).board
        except (OSError, ValueError): return None

    def _color(self, tileset, t):
        c = self._tile_color.get((id(tileset), t))
        if c is None:
            sx, sy = render.tile_src(t); c = self._tile_color[(id(tileset), t)] = tileset.crop((sx, sy, sx + 16, sy + 16)).resize((1, 1), Image.BOX).getpixel((0, 0))
        return c

    def _thumb(self, s, name, board):
        tiledefs = s.weapons.get("TileDefs", b"").replace(b"\xa7", b"\n").decode("latin1")
        tileset = render.tileset_for(name, tiledefs, [], [])
        im = Image.new("RGBA", (LEVEL_PX, LEVEL_PX))
        im.putdata([self._color(tileset, (board[2 * i] | (board[2 * i + 1] << 8)) & 0xFFF) for i in range(LEVEL_PX * LEVEL_PX)])
        return im

    def update(self, s, budget=PER_FRAME):
        """Make the pictures of up to `budget` levels that are not done yet. Returns the number made."""
        rows = s.gmap_rows() or []; made = 0
        for row in rows:
            for name in row:
                if name in self.thumbs: continue
                board = self._board(s, name)
                if board is None: continue
                self.thumbs[name] = self._thumb(s, name, board); made += 1
                if made >= budget: return made
        return made

    def players(self, s, rows):
        """The other players on this gmap: [(nick, account, cell_x, cell_y, x_px, y_px, live)].

        gs2emu gives a player on a gmap the gmap's own name as level and the cell in GMAPLEVELX / GMAPLEVELY; a server that sends the level file name is
        handled too (the cell is where that file is in the gmap)."""
        cells = {n: (x, y) for y, r in enumerate(rows) for x, n in enumerate(r)}; out = []
        for pid, o in s.online.items():
            account, level = str(o.get("ACCOUNTNAME") or ""), str(o.get("LEVEL") or "")
            if not account or account.startswith("("): continue
            live = s.map_positions.get(account)
            if live and (level.lower() == (s.gmap or "").lower() or level in cells) and time.time() - live[3] < LIVE_SECS:
                cell = (int(live[1] // 1024), int(live[2] // 1024)); out.append((str(o.get("NICKNAME") or account), account, cell[0], cell[1], live[1] % 1024, live[2] % 1024, True)); continue
            if level.lower() == (s.gmap or "").lower() and "GMAPLEVELX" in o: cell = (o["GMAPLEVELX"], o.get("GMAPLEVELY", 0))
            elif level in cells: cell = cells[level]
            else: continue
            if not (0 <= cell[1] < len(rows) and 0 <= cell[0] < len(rows[0])): continue
            out.append((str(o.get("NICKNAME") or account), account, cell[0], cell[1], o.get("X2", 512), o.get("Y2", 512), False))
        return sorted(out, key=lambda p: p[0].lower())

    @staticmethod
    def is_near(here, cx, cy):
        """gs2emu only sends the moves of players close to us, so a player this far away is shown where the server last said they were."""
        return here is not None and max(abs(here[0] - cx), abs(here[1] - cy)) <= NEAR

    def own_cell(self, s, rows):
        for y, r in enumerate(rows):
            if s.level_name in r: return r.index(s.level_name), y
        return s.cell

    def mouse(self, x, y): self.hover = (x, y)

    def draw(self, canvas, s):
        if not self.open: return
        w, h = canvas.size; d = ImageDraw.Draw(canvas, "RGBA"); rows = s.gmap_rows() if s.gmap else None
        d.rectangle((0, 0, w, h), fill=(8, 10, 14, 235))
        if not rows or not rows[0]:
            d.text((w // 2 - 90, h // 2 - 6), "There is no map for this level.   M = close", fill=(230, 230, 220, 255)); return
        if self.gmap != s.gmap: self.gmap, self.thumbs, self._base = s.gmap, {}, None
        self.update(s); s.request_map_players()
        cols, nrows = len(rows[0]), len(rows)
        if self._base is None or self._base_count != len(self.thumbs):
            base = Image.new("RGBA", (cols * LEVEL_PX, nrows * LEVEL_PX), UNKNOWN)
            for y, row in enumerate(rows):
                for x, name in enumerate(row):
                    if name in self.thumbs: base.paste(self.thumbs[name], (x * LEVEL_PX, y * LEVEL_PX))
            self._base, self._base_count = base, len(self.thumbs)
        top, side = 26, 170; box_w, box_h = w - side - 16, h - top - 12
        cs = max(2, min(box_w // cols, box_h // nrows)); mw, mh = cols * cs, nrows * cs; ox, oy = 8 + (box_w - mw) // 2, top + (box_h - mh) // 2
        canvas.alpha_composite(self._base.resize((mw, mh), Image.NEAREST if cs >= LEVEL_PX else Image.BOX), (ox, oy))
        d.rectangle((ox - 1, oy - 1, ox + mw, oy + mh), outline=(240, 220, 130, 255))
        for i in range(1, cols): d.line((ox + i * cs, oy, ox + i * cs, oy + mh - 1), fill=(0, 0, 0, 70))
        for j in range(1, nrows): d.line((ox, oy + j * cs, ox + mw - 1, oy + j * cs), fill=(0, 0, 0, 70))
        pending = sum(1 for r in rows for n in r if n not in self.thumbs)
        d.text((8, 8), "Map: %s   %d x %d levels%s   M / Esc = close" % (os.path.splitext(s.gmap)[0], cols, nrows, "   loading %d ..." % pending if pending else ""), fill=(255, 255, 255, 255))
        others = self.players(s, rows); dot = max(3, cs // 6)
        here = self.own_cell(s, rows)
        for nick, account, cx, cy, px, py, live in others:
            x, y = ox + int((cx + min(1.0, max(0.0, px / 1024))) * cs), oy + int((cy + min(1.0, max(0.0, py / 1024))) * cs); col = player_color(account)
            if live or self.is_near(here, cx, cy): d.ellipse((x - dot, y - dot, x + dot, y + dot), fill=col + (255,), outline=(0, 0, 0, 255))
            else: d.ellipse((x - dot, y - dot, x + dot, y + dot), outline=col + (255,), width=2)
            d.text((x + dot + 2, y - 5), nick[:14] + ("" if live or self.is_near(here, cx, cy) else " ?"), fill=(255, 255, 255, 255))
        cell = self.own_cell(s, rows)
        if cell is not None and s.level_name:
            mx, my = ox + int((cell[0] + min(1.0, max(0.0, s.pos[0] / 1024))) * cs), oy + int((cell[1] + min(1.0, max(0.0, s.pos[1] / 1024))) * cs)
            blink = int(time.time() * 2) % 2 == 0
            d.ellipse((mx - dot - 1, my - dot - 1, mx + dot + 1, my + dot + 1), outline=(255, 255, 255, 255), width=2, fill=(255, 60, 60, 255) if blink else (255, 255, 255, 255))
        px0 = w - side; d.text((px0, 8), "Players on this map: %d" % len(others), fill=(255, 240, 160, 255))
        for i, (nick, account, cx, cy, px, py, live) in enumerate(others[:30]):
            col = player_color(account); d.ellipse((px0, top + i * 14 + 3, px0 + 6, top + i * 14 + 9), fill=col + (255,)); d.text((px0 + 12, top + i * 14), nick[:22], fill=(235, 235, 225, 255))
        d.text((px0, h - 52), "filled = nearby, live", fill=(190, 190, 180, 255)); d.text((px0, h - 40), "ring + ? = last known", fill=(190, 190, 180, 255))
        if len(others) > 30: d.text((px0, top + 30 * 14), "... and %d more" % (len(others) - 30), fill=(190, 190, 180, 255))
        if self.hover and ox <= self.hover[0] < ox + mw and oy <= self.hover[1] < oy + mh:
            gx, gy = int((self.hover[0] - ox) // cs), int((self.hover[1] - oy) // cs)
            d.text((px0, h - 22), "%s (%d,%d)" % (rows[gy][gx], gx, gy), fill=(230, 230, 220, 255))
