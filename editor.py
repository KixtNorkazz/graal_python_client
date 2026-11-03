"""Build: the level editor for .nw levels, after the editor of the original Graal client.

  python3 editor.py [level.nw] [--dir FOLDER]       FOLDER is where levels are opened from and saved to (default: the first asset folder in paths.json, else ./levels)

Tools (keys or the toolbar):  T tiles - paint with the tiles picked in the palette, right button drag picks tiles from the level      F flood fill
                              S select - drag a rectangle, Ctrl+C / Ctrl+X / Delete / Ctrl+V      O objects - NPC (N), chest (C), baddy (B); click to place, drag to move
                              L links - drag a warp rectangle      I signs - click a tile
The buttons down the right edge pick the tool and run the actions; Character and Empty NPC are dragged onto the level.
Tab switches the palette between tiles, saved tile objects (Ctrl+B saves the picked tiles) and NPC templates (Ctrl+Shift+B saves the selected NPC).
[ and ] change the layer, + and - zoom, K makes the picked tile the background tile, arrows / wheel scroll the level (over the palette: the whole tileset, sideways),
PageUp / PageDown jump a screen of tiles in the palette, F2 grid, the Tileset button chooses the tileset image, the Image button the picture for new NPCs,
Ctrl+N new, Ctrl+O open, Ctrl+S save, Ctrl+Shift+S save as, Ctrl+Z undo, Ctrl+Y redo, P play the level offline."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import json, os, subprocess, sys, tempfile, time
from PIL import Image, ImageDraw
import assets, config, render, window
from buildlib import Library
from editor_forms import Field, Form
from filebrowser import FileBrowser
import charsprite
from npc_snippets import CHARACTER_SCRIPT, SNIPPETS
from leveldoc import BADDY_NAMES, CHEST_ITEMS, EMPTY, MAX_LAYER, LevelDoc, Pattern, SIZE

SIDE_W = 84
W, H, TOOLBAR_H, STATUS_H, PAL_W = 960 + SIDE_W, 640, 0, 16, 272
VX, VY, VW, VH = PAL_W, TOOLBAR_H, W - PAL_W - SIDE_W, H - TOOLBAR_H - STATUS_H
T = 16
PAL_Y = TOOLBAR_H + 40
PAL_COLS, TILE_COLS = 16, 128
IMAGE_EXTS = (".png", ".gif", ".mng")
DOUBLE_CLICK = 0.4
K_DELETE, K_PGUP, K_PGDN, K_F2 = 127, 0x4000004B, 0x4000004E, 0x4000003B
TOOLS = (("t", "tile", "Tiles"), ("f", "fill", "Fill"), ("s", "select", "Select"), ("o", "object", "Objects"), ("l", "link", "Links"), ("i", "sign", "Signs"))
BTN_H, BTN_STEP = 19, 21
QUICK = (("Character", "-", CHARACTER_SCRIPT, False), ("Empty NPC", "-", "", True))
ACTIONS = (("New", "n", 1), ("Open", "o", 1), ("Save", "s", 1), ("Undo", "z", 1), ("Redo", "y", 1), ("Copy", "c", 1), ("Cut", "x", 1), ("Paste", "v", 1), ("Play", "p", 0))
OBJ_KINDS = (("n", "npc"), ("c", "chest"), ("b", "baddy"))
PAL_MODES = (("tiles", "Tiles"), ("objects", "Objects"), ("npcs", "NPCs"))
TAB_STEP, TAB_W = 70, 66
COLORS = dict(link=(80, 160, 255), sign=(255, 230, 90), chest=(255, 150, 60), baddy=(255, 80, 80), npc=(120, 255, 140))


def default_dir():
    for d in config.dirs("asset_dirs"):
        if os.path.isdir(d): return d
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "levels")


class Editor:
    def __init__(self, folder=None, path=None, library=None):
        self.dir = folder or default_dir(); os.makedirs(self.dir, exist_ok=True)
        self.lib = library or Library()
        cache = config.CFG.get("cache_dir")
        if cache and os.path.isdir(cache):
            for sub in sorted(os.listdir(cache)):
                if os.path.isdir(os.path.join(cache, sub)): assets.add_root(os.path.join(cache, sub))
        self.mod = 0; self.msg = ""; self.modal = None; self.modal_cb = None
        self.tool, self.obj_kind, self.grid, self.layer, self.zoom = "select", "npc", False, 0, 1
        self.pattern = Pattern.single(0); self.pal_x = 0; self.pal_drag = False; self.pal_hover = None; self.last_click = (None, 0); self.drag_new = None
        self.base = self.lib.setting("tileset") or render.BASE_TILESET; self.npc_image = "-"; self.pal_mode = "tiles"; self.pal_item = None; self.npc_template = None
        self.cam = [0, 0]; self.mouse = (0, 0); self.cell = None
        self.stroke = self.last = self.pick = self.sel = self.sel_start = self.pal_start = self.pal_sel = self.link_start = self.link_end = None
        self.clip = None; self.clip_objs = []; self.moving = None; self.move_from = None; self.pasting = False; self.selected = None; self.drag_from = None; self.drag_began = False
        self.doc = None; self.tileset = None; self.level_img = None
        self.open_doc(LevelDoc.load(path) if path else LevelDoc("untitled.nw"))

    def open_doc(self, doc):
        self.doc = doc; self.selected = self.sel = None; self.cam = [0, 0]; self.layer = 0; self.refresh_all()

    def refresh_all(self):
        self.tileset = render.tileset_for(self.doc.name, "", [n["script"] for n in self.doc.npcs], base=self.base)
        self.level_img = render.render_level_tiles(self.doc.board(), self.tileset)
        for layer in sorted(self.doc.layers):
            for i, t in enumerate(self.doc.layers[layer]):
                if t != EMPTY: self.level_img.alpha_composite(self._tile_img(t), (i % SIZE * T, i // SIZE * T))

    def _tile_img(self, t):
        sx, sy = render.tile_src(t & 0xFFF); return self.tileset.crop((sx, sy, sx + T, sy + T))

    def put_tile(self, x, y):
        self.level_img.paste(self._tile_img(self.doc.tile(x, y)), (x * T, y * T))
        for layer in sorted(self.doc.layers):
            t = self.doc.tile(x, y, layer)
            if t != EMPTY: self.level_img.alpha_composite(self._tile_img(t), (x * T, y * T))

    def say(self, text): self.msg = text

    def path(self, name=None): return os.path.join(self.dir, name or self.doc.name)

    def view_size(self): return VW // self.zoom, VH // self.zoom

    def cell_at(self, x, y):
        if not (VX <= x < VX + VW and VY <= y < VY + VH): return None
        tx, ty = (int(x - VX) // self.zoom + self.cam[0]) // T, (int(y - VY) // self.zoom + self.cam[1]) // T
        return (tx, ty) if 0 <= tx < SIZE and 0 <= ty < SIZE else None

    def scroll(self, dx, dy):
        vw, vh = self.view_size()
        self.cam[0] = max(0, min(SIZE * T - vw, self.cam[0] + dx)); self.cam[1] = max(0, min(SIZE * T - vh, self.cam[1] + dy))

    def set_zoom(self, z):
        self.zoom = z; self.scroll(0, 0)

    def handle(self, ev):
        if ev[0] == "repeat":
            if ev[1] not in window.REPEATING: return
            ev = ("down", ev[1])
        if self.modal is not None:
            r = self.modal.handle(ev, self.mod)
            if r is not None: cb, self.modal, self.modal_cb = self.modal_cb, None, None; cb(r)
            return
        kind = ev[0]
        if kind == "down": self._key(ev[1])
        elif kind == "mousemove": self._move(ev[1], ev[2])
        elif kind == "mousedown": self._down(ev[1], ev[2], ev[3])
        elif kind == "mouseup": self._up(ev[1], ev[2], ev[3])
        elif kind == "wheel":
            if self.mouse[0] < PAL_W and self.pal_mode == "tiles": self.scroll_palette(-ev[1] * 4)
            else: self.scroll(0, -ev[1] * 32)

    def ask(self, dialog, callback): self.modal, self.modal_cb = dialog, callback

    def _key(self, k):
        ctrl, shift = bool(self.mod & window.KMOD_CTRL), bool(self.mod & window.KMOD_SHIFT)
        ch = chr(k) if 32 <= k < 127 else ""
        if ctrl and ch:
            if ch == "z": self.undo()
            elif ch == "y": self.redo()
            elif ch == "n": self.new_level()
            elif ch == "o": self.open_level()
            elif ch == "s": self.save(as_new=shift)
            elif ch == "c": self.copy_selection()
            elif ch == "x": self.copy_selection(cut=True)
            elif ch in ("v", "p"): self.start_paste()
            elif ch == "b": self.save_template() if shift else self.save_object()
            return
        if k == window.K_ESCAPE: self.pasting = False; self.sel = None; self.selected = None
        elif k == K_DELETE: self.delete_selection()
        elif k == window.K_RETURN and self.selected: self.edit_selected()
        elif k == window.K_TAB: self.next_palette()
        elif k in (window.K_LEFT, window.K_RIGHT) and self.mouse[0] < PAL_W and self.pal_mode == "tiles": self.scroll_palette(-1 if k == window.K_LEFT else 1)
        elif k in (window.K_LEFT, window.K_RIGHT, window.K_UP, window.K_DOWN):
            self.scroll({window.K_LEFT: -64, window.K_RIGHT: 64}.get(k, 0), {window.K_UP: -64, window.K_DOWN: 64}.get(k, 0))
        elif k in (K_PGUP, K_PGDN): self.scroll_palette(PAL_COLS if k == K_PGDN else -PAL_COLS)
        elif k == K_F2: self.grid = not self.grid
        elif ch in ("[", "]"): self.change_layer(1 if ch == "]" else -1)
        elif ch in ("+", "="): self.set_zoom(2)
        elif ch == "-": self.set_zoom(1)
        elif ch == "p": self.play()
        elif ch == "k": self.doc.backtile = self.pattern.tiles[0]; self.say("background tile %d" % self.doc.backtile)
        elif self.tool == "object" and ch in dict(OBJ_KINDS): self.obj_kind = dict(OBJ_KINDS)[ch]
        else:
            for key, tool, _ in TOOLS:
                if ch == key: self.tool = tool; self.pasting = False

    def change_layer(self, d):
        self.layer = max(0, min(MAX_LAYER, self.layer + d)); self.say("layer %d" % self.layer)

    def scroll_palette(self, cols): self.pal_x = max(0, min(TILE_COLS - PAL_COLS, self.pal_x + cols))

    def next_palette(self):
        names = [m for m, _ in PAL_MODES]; self.pal_mode = names[(names.index(self.pal_mode) + 1) % len(names)]; self.pal_item = None; self.pal_sel = None

    def undo(self):
        if self.doc.undo(): self.refresh_all(); self.selected = None; self.say("undo")

    def redo(self):
        if self.doc.redo(): self.refresh_all(); self.selected = None; self.say("redo")

    def copy_selection(self, cut=False):
        if not self.sel: self.say("select an area first (S)"); return
        pat = self.doc.copy_rect(*self.sel, self.layer)
        if pat is None: return
        self.clip = self.pattern = pat; self.clip_objs = self.doc.copy_objects(*self.sel)
        self.say("%s %dx%d tiles and %d objects (Ctrl+V or Ctrl+P pastes)" % ("cut" if cut else "copied", pat.w, pat.h, len(self.clip_objs)))
        if cut: self.doc.begin(); self.doc.clear_rect(*self.sel, self.layer); self.doc.remove_objects(self.doc.objects_in(*self.sel)); self.selected = None; self.refresh_all()

    def _move_selection(self, c):
        """Dragging inside the selection: the first step lifts its tiles (this layer) and every object in it; then they follow the mouse."""
        if self.moving is None:
            self.doc.begin(); pat = self.doc.copy_rect(*self.sel, self.layer); hits = self.doc.objects_in(*self.sel)
            self.doc.clear_rect(*self.sel, self.layer); self.moving = dict(pat=pat, hits=hits, off=(0, 0)); self.refresh_all()
        ox, oy = self.moving["off"]; nx, ny = c[0] - self.move_from[0], c[1] - self.move_from[1]
        x, y, w, h = self.sel; nx = max(-x, min(SIZE - x - w, nx)); ny = max(-y, min(SIZE - y - h, ny))
        if (nx, ny) != (ox, oy): self.doc.shift_objects(self.moving["hits"], nx - ox, ny - oy); self.moving["off"] = (nx, ny)

    def _drop_selection(self):
        m = self.moving; self.moving = None; (dx, dy) = m["off"]; x, y, w, h = self.sel
        self.doc.paste(x + dx, y + dy, m["pat"], self.layer); self.sel = (x + dx, y + dy, w, h); self.refresh_all()
        self.say("moved %dx%d tiles and %d objects" % (w, h, len(m["hits"])))

    def start_paste(self):
        if self.clip is None: self.say("nothing copied yet"); return
        self.tool, self.pasting = "select", True; self.say("click to paste, Esc cancels")

    def delete_selection(self):
        if self.pal_mode != "tiles" and self.pal_item is not None: self._delete_palette_item(); return
        if self.selected:
            self.doc.remove(*self.selected); self.selected = None; self.say("object deleted")
        elif self.sel:
            self.doc.begin(); self.doc.clear_rect(*self.sel, self.layer); self.doc.remove_objects(self.doc.objects_in(*self.sel)); self.refresh_all(); self.say("area cleared")

    def save_object(self):
        if self.pattern.w * self.pattern.h < 2 and not self.sel: self.say("pick more than one tile first"); return
        self.lib.add_object(self.pattern); self.say("saved as object %d (Tab shows the objects)" % len(self.lib.objects))

    def save_template(self):
        if not self.selected or self.selected[0] != "npc": self.say("select an NPC first (O tool)"); return
        n = self.doc.npcs[self.selected[1]]
        def go(r):
            if r[0] == "ok" and self.lib.save_npc(r[1]["name"], n["image"], n["script"]): self.say("saved NPC template " + r[1]["name"])
        self.ask(Form("Save NPC as template", [Field("name", "Name:", "")], check=lambda v: "Use letters, digits, - and _." if not v["name"].strip() else ""), go)

    def _delete_palette_item(self):
        if self.pal_mode == "objects": self.lib.remove_object(self.pal_item)
        else: self.lib.remove_npc(self.lib.npc_names()[self.pal_item]); self.npc_template = None
        self.pal_item = None; self.say("deleted")

    def _palette_cell(self, x, y, clamp=False):
        """The tile column (0..127, counted over the whole tileset) and row under a palette position."""
        px, py = x - 8, y - PAL_Y
        if clamp: px, py = max(0, min(255, px)), max(0, min(511, py))
        return (int(px) // T + self.pal_x, int(py) // T) if 0 <= px < 256 and 0 <= py < 512 else None

    @staticmethod
    def tile_number(col, row): return (col // PAL_COLS) * 512 + row * PAL_COLS + col % PAL_COLS

    def _bar_value(self, x): return max(0, min(TILE_COLS - PAL_COLS, int((x - 8) / 256 * TILE_COLS - PAL_COLS / 2)))

    def _object_slots(self):
        """Where the saved tile objects sit in the palette: [(x, y, w, h)] in palette pixels, flowing left to right."""
        slots, x, y, rowh = [], 0, 0, 0
        for o in self.lib.objects:
            w, h = min(o["w"] * T, 256), min(o["h"] * T, 256)
            if x + w > 256: x, y, rowh = 0, y + rowh + 4, 0
            slots.append((x, y, w, h)); x += w + 4; rowh = max(rowh, h)
        return slots

    def _pick_palette_item(self, x, y):
        px, py = x - 8, y - PAL_Y
        if self.pal_mode == "objects":
            for i, (sx, sy, sw, sh) in enumerate(self._object_slots()):
                if sx <= px < sx + sw and sy <= py < sy + sh: self.pal_item = i; self.pattern = self.lib.pattern(i); self.say("object %s" % self.lib.objects[i]["name"]); return
        else:
            i = int(py) // 14; names = self.lib.npc_names()
            if 0 <= px < 256 and 0 <= i < len(names): self.pal_item = i; self.npc_template = names[i]; self.tool, self.obj_kind = "object", "npc"; self.say("drag it onto the level, or click with the object tool"); tpl = self.lib.npc(names[i]); self.drag_new = (tpl[0], tpl[1], False) if tpl else None

    def _pattern_from(self, c0, c1):
        x0, x1 = sorted((c0[0], c1[0])); y0, y1 = sorted((c0[1], c1[1]))
        return Pattern(x1 - x0 + 1, y1 - y0 + 1, [self.tile_number(i, j) for j in range(y0, y1 + 1) for i in range(x0, x1 + 1)])

    def _down(self, button, x, y):
        if x >= W - SIDE_W: self._down_toolbar(x, y); return
        if x < PAL_W and y < PAL_Y:
            if y >= TOOLBAR_H + 24 and x >= PAL_W - 84:
                if self.pal_mode == "tiles": self.choose_tileset()
                elif self.pal_mode == "npcs": self.choose_npc_image()
                return
            for i, (mode, _) in enumerate(PAL_MODES):
                if 8 + i * TAB_STEP <= x < 8 + i * TAB_STEP + TAB_W: self.pal_mode = mode; self.pal_item = None; self.pal_sel = None
            return
        if x < PAL_W and button == 1:
            if self.pal_mode == "tiles":
                if PAL_Y + 514 <= y < PAL_Y + 528: self.pal_x = self._bar_value(x); self.pal_drag = True; return
                pc = self._palette_cell(x, y)
                if pc is not None: self.pal_start = pc; self.pal_sel = (pc, pc); self.pattern = self._pattern_from(pc, pc)
            else: self._pick_palette_item(x, y)
            return
        c = self.cell_at(x, y)
        if c is None: return
        self.cell = c; tx, ty = c
        if button == 3 and self.tool in ("tile", "fill", "select"): self.pick = (c, c); return
        if button != 1: return
        if self.tool == "tile":
            self.doc.begin(); self.stroke = self.last = c
            for j in range(self.pattern.h):
                for i in range(self.pattern.w):
                    if self.doc.inside(tx + i, ty + j): self._paint((tx + i, ty + j))
        elif self.tool == "fill":
            self.doc.begin(); n = self.doc.fill(tx, ty, self.pattern, self.layer); self.refresh_all(); self.say("filled %d tiles" % n)
        elif self.tool == "select":
            if self.pasting:
                self.doc.begin(); self.doc.paste(tx, ty, self.clip, self.layer); n = self.doc.add_objects(self.clip_objs, tx, ty)
                self.sel = (tx, ty, self.clip.w, self.clip.h); self.refresh_all(); self.pasting = False; self.say("pasted %d objects with the tiles" % n if n else "pasted")
            elif self.sel and self.sel[0] <= tx < self.sel[0] + self.sel[2] and self.sel[1] <= ty < self.sel[1] + self.sel[3]: self.move_from = c
            else: self.sel_start = c; self.sel = (tx, ty, 1, 1)
        elif self.tool == "object": self._down_object(c)
        elif self.tool == "link": self._down_link(c)
        elif self.tool == "sign": self._down_sign(c)

    @staticmethod
    def side_buttons():
        """The buttons down the right edge: [(y, kind, label, arg)] with kind tool, new (drag out onto the level) or action."""
        out, y = [], 6
        for key, tool, label in TOOLS: out.append((y, "tool", "%s %s" % (key.upper(), label), tool)); y += BTN_STEP
        y += 8
        for name, image, script, edit in QUICK: out.append((y, "new", name, (image, script, edit))); y += BTN_STEP
        y += 8
        for name, key, ctrl in ACTIONS: out.append((y, "action", name, (name, key, ctrl))); y += BTN_STEP
        return out

    def _down_toolbar(self, x, y):
        for by, kind, label, arg in self.side_buttons():
            if not by <= y < by + BTN_H: continue
            if kind == "tool": self.tool = arg; self.pasting = False
            elif kind == "new": self.drag_new = arg; self.say("drag it onto the level")
            else:
                name, key, ctrl = arg
                if name == "Save": self.save_as(); return
                saved = self.mod; self.mod = window.KMOD_CTRL if ctrl else 0; self._key(ord(key)); self.mod = saved
            return

    def _paint(self, c):
        sx, sy = self.stroke; t = self.pattern.at(c[0] - sx, c[1] - sy)
        if self.doc.set_tile(c[0], c[1], t, self.layer): self.put_tile(*c)

    def _move(self, x, y):
        self.mouse = (x, y); c = self.cell_at(x, y)
        if self.pal_drag: self.pal_x = self._bar_value(x); return
        if self.pal_start is not None:
            if x < 12: self.scroll_palette(-1)
            elif x > PAL_W - 12: self.scroll_palette(1)
            pc = self._palette_cell(x, y, clamp=True)
            if pc: self.pal_sel = (self.pal_start, pc); self.pattern = self._pattern_from(self.pal_start, pc)
            return
        pc = self._palette_cell(x, y) if self.pal_mode == "tiles" and x < PAL_W else None
        self.pal_hover = self.tile_number(*pc) if pc else None
        if c is None: return
        self.cell = c
        if self.stroke is not None:
            for p in _line(self.last, c):
                if self.doc.inside(*p): self._paint(p)
            self.last = c
        elif self.pick is not None: self.pick = (self.pick[0], c)
        elif self.move_from is not None and (self.moving is not None or c != self.move_from): self._move_selection(c)
        elif self.sel_start is not None:
            x0, x1 = sorted((self.sel_start[0], c[0])); y0, y1 = sorted((self.sel_start[1], c[1])); self.sel = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
        elif self.link_start is not None: self.link_end = c
        elif self.drag_from is not None and self.selected and c != self.drag_from:
            self.doc.move(*self.selected, c[0] - self.drag_from[0], c[1] - self.drag_from[1], record=not self.drag_began); self.drag_began = True; self.drag_from = c

    def _drop_npc(self, c, image, script, edit):
        self.doc.add_npc(c[0], c[1], image, script); index = len(self.doc.npcs) - 1; self.selected = ("npc", index); self.refresh_all()
        gone = charsprite.missing(script)
        self.say("NPC placed, double-click it to edit" if not gone else "not on this computer: %s (play on the server once so the client downloads it)" % ", ".join(gone))
        if edit: self._edit("npc", index, new=True)

    def _up(self, button, x, y):
        if self.drag_new is not None:
            image, script, edit = self.drag_new; self.drag_new = None; c = self.cell_at(x, y)
            if c is not None: self._drop_npc(c, image, script, edit)
            return
        if self.pal_drag: self.pal_drag = False; return
        if self.pal_start is not None: self.pal_start = None; return
        if self.stroke is not None: self.stroke = None
        if self.pick is not None:
            (x0, y0), (x1, y1) = self.pick; self.pick = None
            pat = self.doc.copy_rect(min(x0, x1), min(y0, y1), abs(x1 - x0) + 1, abs(y1 - y0) + 1, self.layer)
            if pat: self.pattern = pat; self.say("picked %dx%d tiles" % (pat.w, pat.h))
        if self.moving is not None: self._drop_selection()
        self.move_from = None; self.sel_start = None; self.drag_from = None
        if self.link_start is not None:
            a, b = self.link_start, self.link_end or self.link_start; self.link_start = self.link_end = None
            self._new_link(min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]) + 1, abs(a[1] - b[1]) + 1)

    def _down_object(self, c):
        hits = [h for h in self.doc.objects_at(*c) if h[0] != "link"]
        if hits:
            now = time.monotonic(); again = self.selected == hits[0] and self.last_click[0] == c and now - self.last_click[1] < DOUBLE_CLICK
            self.last_click = (c, now); self.selected = hits[0]; self.drag_from = c; self.drag_began = False
            if again: self.drag_from = None; self.edit_selected()
            return
        self.selected = None
        if self.obj_kind == "npc":
            image, script = (self.lib.npc(self.npc_template) if self.npc_template else None) or (self.npc_image, "")
            self.doc.add_npc(c[0], c[1], image, script); kind = "npc"
        elif self.obj_kind == "chest": self.doc.add_chest(c[0], c[1]); kind = "chest"
        else: self.doc.add_baddy(c[0], c[1]); kind = "baddy"
        self._edit(kind, len(self.doc.objects(kind)) - 1, new=True)

    def _down_sign(self, c):
        hit = [h for h in self.doc.objects_at(*c) if h[0] == "sign"]
        if hit: self._edit(*hit[0])
        else: self.doc.add_sign(c[0], c[1]); self._edit("sign", len(self.doc.signs) - 1, new=True)

    def _down_link(self, c):
        hit = [h for h in self.doc.objects_at(*c) if h[0] == "link"]
        if hit: self._edit(*hit[0])
        else: self.link_start = self.link_end = c

    def _new_link(self, x, y, w, h):
        self.doc.add_link("", x, y, w, h, "30", "30"); self._edit("link", len(self.doc.links) - 1, new=True)

    def edit_selected(self):
        if self.selected: self._edit(*self.selected)

    def _edit(self, kind, index, new=False, preset=None):
        o = self.doc.objects(kind)[index]
        if kind == "link":
            fields = [Field("level", "Link to level:", o["level"])] + [Field(k, l, o[k], width=10) for k, l in (("x", "X:"), ("y", "Y:"), ("w", "W:"), ("h", "H:"), ("nx", "New X:"), ("ny", "New Y:"))]
            check = lambda v: "Type in a level file name." if not v["level"].strip() else "X, Y, W, H must be whole numbers inside the level." if not _ints(v, "x", "y", "w", "h") else ""
            form = Form("Edit link", fields, ("delete",), "New X / New Y can be numbers (tiles) or playerx / playery.", check)
        elif kind == "sign":
            form = Form("Edit sign", [Field("text", "Text:", o["text"], lines=6, width=44)], ("delete",), "#b = line break, #1 ... special graphics codes as in the original editor.")
        elif kind == "chest":
            form = Form("Edit chest", [Field("item", "Item:", o["item"]), Field("sign", "Sign index:", o["sign"], width=6)], ("delete",), "Items: " + ", ".join(CHEST_ITEMS[:12]) + " ...",
                        lambda v: "Unknown item." if v["item"] not in CHEST_ITEMS else "Sign index must be a number." if not _ints(v, "sign") else "")
        elif kind == "baddy":
            form = Form("Edit baddy", [Field("type", "Type 0-9:", o["type"], width=4)] + [Field("v%d" % i, l, o["verses"][i]) for i, l in enumerate(("Attack verse:", "Hurt verse:", "Player hurt verse:"))], ("delete",),
                        "Types: " + ", ".join("%d %s" % (i, n) for i, n in enumerate(BADDY_NAMES[:5])) + " ...", lambda v: "Type must be 0 to 9." if not (_ints(v, "type") and 0 <= int(v["type"]) <= 9) else "")
        else:
            preset = preset or {}
            form = Form("Edit NPC", [Field("image", "Image:", preset.get("image", o["image"]), width=100), Field("script", "Script:", preset.get("script", o["script"]), lines=26, width=100)], ("delete", "image", "load", "snippet"),
                        "F1 delete   F2 pick image   F3 load script from a file   F4 insert an example script.  The script runs on the server (//#CLIENTSIDE for the client).", width=900)
            form.focus = preset.get("focus", 0)
        self.ask(form, lambda r: self._edited(kind, index, new, r))

    def _edited(self, kind, index, new, r):
        name, v = r
        if name in ("image", "load", "snippet"): self._npc_helper(name, v, index, new); return
        if name == "cancel":
            if new: self.doc.undo()
            return
        if name == "delete":
            if new: self.doc.undo()
            else: self.doc.remove(kind, index)
            self.selected = None; self.say("%s deleted" % kind); return
        o = self.doc.objects(kind)[index]; fields = dict(v)
        if kind == "baddy": fields = dict(type=int(v["type"]), verses=[v["v0"], v["v1"], v["v2"]])
        elif kind == "chest": fields["sign"] = int(v["sign"])
        elif kind == "link":
            for k in ("x", "y", "w", "h"): fields[k] = int(v[k])
        elif kind == "sign": fields["text"] = v["text"].rstrip("\n")
        if new: o.update(fields)
        else: self.doc.edit(kind, index, **fields)
        if kind == "npc": self.refresh_all()
        self.selected = (kind, index)

    def _npc_helper(self, what, v, index, new):
        """F2 / F3 / F4 of the NPC dialog: choose an image, a script file or an example, then come back to the dialog with the text kept."""
        def back(**changes):
            v.update(changes); self._edit("npc", index, new, dict(v, focus=1))
        if what == "image":
            self._pick_image(lambda name: back(image=name) if name else back())
        elif what == "load":
            def got(r):
                if r[0] != "ok": back(); return
                try:
                    with open(r[1], encoding="latin1") as f: text = f.read().replace("\r", "").rstrip("\n")
                except OSError: self.say("could not read " + r[1]); back(); return
                back(script=text)
            self.ask(FileBrowser("Load script from a file", self.dir, (".txt", ".gs2", ".gs1", ".nw"), preview=False), got)
        else:
            names = [(label, label) for label, _ in SNIPPETS]
            def got(r):
                code = dict(SNIPPETS).get(os.path.basename(r[1])) if r[0] == "ok" else None
                back(script=(v["script"].rstrip("\n") + "\n" if v["script"].strip() else "") + code) if code else back()
            self.ask(FileBrowser("Insert an example script", None, flat=names), got)

    def _pick_image(self, done, title="Choose an image"):
        from assets import index
        items = sorted(((n, p) for n, p in index().items() if os.path.splitext(n)[1] in IMAGE_EXTS), key=lambda t: t[0])
        def got(r): done(os.path.basename(r[1]) if r[0] == "ok" else None)
        self.ask(FileBrowser(title, None, flat=items, preview=True), got)

    def choose_npc_image(self):
        def got(name):
            if name: self.npc_image = name; self.npc_template = None; self.pal_item = None; self.tool, self.obj_kind = "object", "npc"; self.say("new NPCs use the image " + name)
        self._pick_image(got)

    def choose_tileset(self):
        def got(name):
            if not name: return
            if render.load_image(name) is None: self.say("could not read the image " + name); return
            self.base = name; self.lib.set_setting("tileset", name); self.pal_x = 0; self.refresh_all(); self.say("tileset " + name)
        self._pick_image(got, "Choose the tileset image")

    def new_level(self):
        def go(r):
            if r[0] == "ok":
                name = r[1]["name"].strip(); name = name if name.lower().endswith(".nw") else name + ".nw"
                self.open_doc(LevelDoc(name)); self.say("new level " + name)
        def start(_=None): self.ask(Form("New level", [Field("name", "File name:", "")], check=lambda v: "Type a file name." if not v["name"].strip() else ""), go)
        self._unsaved(start)

    def open_level(self):
        def go(r):
            if r[0] != "ok": return
            try: doc = LevelDoc.load(r[1])
            except OSError: self.say("could not open " + r[1]); return
            self.dir = os.path.dirname(r[1]); self.open_doc(doc); self.say("opened " + r[1])
        self._unsaved(lambda _=None: self.ask(FileBrowser("Open level", self.dir, (".nw",)), go))

    def _unsaved(self, then):
        if not self.doc.modified: then(); return
        form = Form("Unsaved changes in %s" % self.doc.name, [Field("answer", "Discard them? yes / no:", "")])
        self.ask(form, lambda r: then() if r[0] == "ok" and r[1]["answer"].strip().lower() in ("y", "yes") else None)

    def save(self, as_new=False):
        if as_new or self.doc.name == "untitled.nw": self.save_as(); return
        self._write(self.path())

    def save_as(self):
        def go(r):
            if r[0] != "ok": return
            path = r[1] if r[1].lower().endswith(".nw") else r[1] + ".nw"
            if os.path.exists(path) and os.path.abspath(path) != os.path.abspath(self.path()):
                self.ask(Form("%s exists" % os.path.basename(path), [Field("answer", "Overwrite? yes / no:", "")]), lambda r2: self._write(path) if r2[0] == "ok" and r2[1]["answer"].strip().lower() in ("y", "yes") else None)
            else: self._write(path)
        self.ask(FileBrowser("Save level", self.dir, (".nw",), save=True, name=self.doc.name if self.doc.name != "untitled.nw" else ""), go)

    def _write(self, path):
        try: self.doc.save(path)
        except OSError: self.say("could not save " + path); return
        self.dir = os.path.dirname(os.path.abspath(path)); self.say("saved " + path)

    def play(self):
        if self.doc.name == "untitled.nw": self.say("save the level under a name before playing"); return
        self.doc.save(self.path()); here = os.path.dirname(os.path.abspath(__file__))
        cfg = dict(config.CFG); folders = [self.dir] + [d for d in config.CFG["asset_dirs"] if d != self.dir]
        tmp = os.path.join(tempfile.gettempdir(), "graal_editor_paths.json")
        with open(tmp, "w") as f: json.dump(dict(asset_dirs=folders, class_dirs=cfg["class_dirs"], weapon_dirs=cfg["weapon_dirs"], server_script_dirs=cfg["server_script_dirs"]), f)
        subprocess.Popen([sys.executable, os.path.join(here, "viewer.py"), "--offline", self.doc.name], env=dict(os.environ, GRAAL_PATHS=tmp, GRAAL_BASE_TILESET=self.base), cwd=here)
        self.say("started the level in a new window")

    def draw(self):
        im = Image.new("RGBA", (W, H), (22, 28, 24, 255)); d = ImageDraw.Draw(im, "RGBA")
        self._draw_toolbar(d); self._draw_palette(im, d); self._draw_view(im); self._draw_status(d)
        if self.drag_new is not None and self.mouse[0] < W - SIDE_W: self._draw_ghost(im)
        if self.modal is not None:
            shade = Image.new("RGBA", (W, H), (0, 0, 0, 110)); im.alpha_composite(shade); self.modal.draw(im)
        return im

    def _draw_toolbar(self, d):
        x0 = W - SIDE_W; d.rectangle((x0, 0, W, H - STATUS_H), fill=(36, 44, 40, 255))
        for y, kind, label, arg in self.side_buttons():
            on = kind == "tool" and self.tool == arg
            fill = (250, 250, 244, 255) if on else (50, 100, 60, 255) if kind == "new" else (60, 70, 66, 255)
            d.rectangle((x0 + 4, y, W - 4, y + BTN_H), fill=fill, outline=(240, 220, 130, 255) if on else (90, 100, 96, 255))
            d.text((x0 + 9, y + 4), label, fill=(20, 20, 20, 255) if on else (230, 230, 220, 255))

    def _draw_palette(self, im, d):
        d.rectangle((0, TOOLBAR_H, PAL_W, H - STATUS_H), fill=(30, 36, 34, 255))
        for i, (mode, label) in enumerate(PAL_MODES):
            on = self.pal_mode == mode; x = 8 + i * TAB_STEP
            d.rectangle((x, TOOLBAR_H + 4, x + 66, TOOLBAR_H + 20), fill=(250, 250, 244, 255) if on else (60, 70, 66, 255), outline=(90, 100, 96, 255))
            d.text((x + 6, TOOLBAR_H + 8), label, fill=(20, 20, 20, 255) if on else (230, 230, 220, 255))
        if self.pal_mode == "tiles": self._draw_tile_palette(im, d)
        elif self.pal_mode == "objects": self._draw_object_palette(im, d)
        else: self._draw_npc_palette(d)

    def _draw_tile_palette(self, im, d):
        d.text((8, TOOLBAR_H + 27), "tileset %s" % self.base[:22], fill=(230, 230, 220, 255)); self._button(d, PAL_W - 84, TOOLBAR_H + 24, "Tileset...")
        im.alpha_composite(self.tileset.crop((self.pal_x * T, 0, self.pal_x * T + 256, 512)), (8, PAL_Y))
        d.rectangle((8, PAL_Y, 8 + 256, PAL_Y + 512), outline=(90, 100, 96, 255))
        if self.pal_sel:
            (a, b), (c, e) = self.pal_sel; x0, x1 = sorted((a, c)); y0, y1 = sorted((b, e))
            if x1 >= self.pal_x and x0 < self.pal_x + PAL_COLS:
                lo, hi = max(x0, self.pal_x), min(x1, self.pal_x + PAL_COLS - 1)
                d.rectangle((8 + (lo - self.pal_x) * T, PAL_Y + y0 * T, 8 + (hi - self.pal_x + 1) * T - 1, PAL_Y + (y1 + 1) * T - 1), outline=(255, 240, 120, 255), width=2)
        by = PAL_Y + 516; d.rectangle((8, by, 264, by + 10), fill=(50, 58, 54, 255), outline=(90, 100, 96, 255))
        tx = 8 + self.pal_x * 256 // TILE_COLS; d.rectangle((tx, by, tx + 256 * PAL_COLS // TILE_COLS, by + 10), fill=(240, 220, 130, 255))
        d.text((8, by + 14), "wheel / bar / PgUp PgDn scroll the tileset", fill=(190, 190, 180, 255))
        if not self.tileset.getbbox(): d.text((12, PAL_Y + 8), "no tileset image found (Tileset...)", fill=(255, 150, 130, 255))

    @staticmethod
    def _button(d, x, y, text):
        d.rectangle((x, y, x + 76, y + 13), fill=(60, 70, 66, 255), outline=(240, 220, 130, 255)); d.text((x + 5, y + 2), text, fill=(240, 240, 230, 255))

    def _draw_object_palette(self, im, d):
        d.text((8, TOOLBAR_H + 26), "Ctrl+B saves the picked tiles here", fill=(230, 230, 220, 255))
        if not self.lib.objects: d.text((12, PAL_Y + 8), "(no saved objects yet)", fill=(190, 190, 180, 255))
        for i, (o, (sx, sy, sw, sh)) in enumerate(zip(self.lib.objects, self._object_slots())):
            for j in range(min(o["h"], sh // T)):
                for k in range(min(o["w"], sw // T)): im.alpha_composite(self._tile_img(o["tiles"][j * o["w"] + k]), (8 + sx + k * T, PAL_Y + sy + j * T))
            d.rectangle((8 + sx, PAL_Y + sy, 8 + sx + sw - 1, PAL_Y + sy + sh - 1), outline=(255, 240, 120, 255) if i == self.pal_item else (90, 100, 96, 255), width=2 if i == self.pal_item else 1)

    def _draw_npc_palette(self, d):
        d.text((8, TOOLBAR_H + 27), "new NPC image: %s" % self.npc_image[:18], fill=(230, 230, 220, 255)); self._button(d, PAL_W - 84, TOOLBAR_H + 24, "Image..."); names = self.lib.npc_names()
        if not names: d.text((12, PAL_Y + 8), "(no NPC templates yet)", fill=(190, 190, 180, 255))
        for i, name in enumerate(names):
            on = i == self.pal_item
            if on: d.rectangle((8, PAL_Y + i * 14, 8 + 255, PAL_Y + i * 14 + 13), fill=(250, 250, 244, 255))
            d.text((12, PAL_Y + i * 14 + 1), name[:38], fill=(20, 20, 20, 255) if on else (230, 230, 220, 255))

    def _draw_ghost(self, im):
        image, script, _ = self.drag_new; x, y = self.mouse; z = self.zoom
        ch = charsprite.sprite(script); pic = render.load_image(image) if image not in ("", "-") else None
        if ch is not None: ghost = ch.resize((ch.width * z, ch.height * z), Image.NEAREST) if z > 1 else ch; ox = oy = charsprite.ORIGIN * z
        elif pic is not None: ghost = pic.crop((0, 0, min(pic.width, 64), min(pic.height, 64))); ox = oy = 0
        else: ghost = Image.new("RGBA", (32 * z, 32 * z), (120, 255, 140, 90)); ox = oy = 0
        c = self.cell_at(x, y); px, py = (VX + ((c[0] * T - self.cam[0]) * z), VY + ((c[1] * T - self.cam[1]) * z)) if c else (x, y)
        render._paste_clipped(im, ghost, int(px - ox), int(py - oy))

    def _draw_view(self, im):
        cx, cy = self.cam; z = self.zoom; vw, vh = self.view_size()
        view = self.level_img.crop((cx, cy, cx + vw, cy + vh))
        if z > 1: view = view.resize((vw * z, vh * z), Image.NEAREST)
        layer = Image.new("RGBA", view.size, (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
        def box(x, y, w, h, color, fill=40, width=2): d.rectangle(((x * T - cx) * z, (y * T - cy) * z, ((x + w) * T - cx) * z - 1, ((y + h) * T - cy) * z - 1), fill=color + (fill,), outline=color + (255,), width=width)
        def label(x, y, text, color=(255, 255, 255, 255)): d.text(((x * T - cx) * z + 2, (y * T - cy) * z + 2), text, fill=color)
        if self.grid:
            for gx in range(cx // T * T, cx + vw, T): d.line(((gx - cx) * z, 0, (gx - cx) * z, vh * z), fill=(0, 0, 0, 50))
            for gy in range(cy // T * T, cy + vh, T): d.line((0, (gy - cy) * z, vw * z, (gy - cy) * z), fill=(0, 0, 0, 50))
        for k in self.doc.links: box(k["x"], k["y"], k["w"], k["h"], COLORS["link"]); label(k["x"], k["y"], k["level"][:14] + " ->" + str(k["nx"]) + "," + str(k["ny"]))
        for s in self.doc.signs: box(s["x"], s["y"], 1, 1, COLORS["sign"], 90); label(s["x"], s["y"], "S")
        for c in self.doc.chests: box(c["x"], c["y"], 1, 1, COLORS["chest"], 90); label(c["x"], c["y"], "C")
        for b in self.doc.baddies: box(int(b["x"]), int(b["y"]), 1, 1, COLORS["baddy"], 90); label(int(b["x"]), int(b["y"]), "B%d" % b["type"])
        for n in self.doc.npcs:
            pic = render.load_image(n["image"]) if n["image"] not in ("", "-") else None
            ch = charsprite.sprite(n["script"]) if pic is None else None
            if ch is not None:
                render._paste_clipped(view, ch.resize((ch.width * z, ch.height * z), Image.NEAREST) if z > 1 else ch, int(n["x"] * T - cx - charsprite.ORIGIN) * z, int(n["y"] * T - cy - charsprite.ORIGIN) * z)
            if pic is not None:
                pic = pic.crop((0, 0, min(pic.width, 64), min(pic.height, 64)))
                render._paste_clipped(view, pic.resize((pic.width * z, pic.height * z), Image.NEAREST) if z > 1 else pic, int(n["x"] * T - cx) * z, int(n["y"] * T - cy) * z)
            box(int(n["x"]), int(n["y"]), 2, 2, COLORS["npc"], 25); label(int(n["x"]), int(n["y"]), "NPC")
        if self.selected and self.selected[1] < len(self.doc.objects(self.selected[0])):
            o = self.doc.objects(self.selected[0])[self.selected[1]]; w, h = (o["w"], o["h"]) if self.selected[0] == "link" else (2, 2) if self.selected[0] == "npc" else (1, 1)
            box(int(o["x"]), int(o["y"]), w, h, (255, 255, 255), 0, 3)
        if self.sel:
            sx_, sy_ = (self.sel[0] + self.moving["off"][0], self.sel[1] + self.moving["off"][1]) if self.moving else self.sel[:2]
            box(sx_, sy_, self.sel[2], self.sel[3], (255, 255, 255), 30, 2)
        if self.pick: (a, b), (c, e) = self.pick; box(min(a, c), min(b, e), abs(a - c) + 1, abs(b - e) + 1, (120, 255, 255), 30)
        if self.link_start: a, b = self.link_start, self.link_end; box(min(a[0], b[0]), min(a[1], b[1]), abs(a[0] - b[0]) + 1, abs(a[1] - b[1]) + 1, COLORS["link"], 60)
        view.alpha_composite(layer)
        ghost = self.clip if self.pasting else self.pattern if self.tool == "tile" else None; at = self.cell; fade = 6
        if self.moving is not None: ghost, at, fade = self.moving["pat"], (self.sel[0] + self.moving["off"][0], self.sel[1] + self.moving["off"][1]), 10
        if ghost is not None and at is not None and not self.stroke:
            for j in range(ghost.h):
                for i in range(ghost.w):
                    t = ghost.tiles[j * ghost.w + i]
                    if t == EMPTY: continue
                    tile = self._tile_img(t); tile.putalpha(tile.getchannel("A").point(lambda a, f=fade: a * f // 10))
                    if z > 1: tile = tile.resize((T * z, T * z), Image.NEAREST)
                    render._paste_clipped(view, tile, ((at[0] + i) * T - cx) * z, ((at[1] + j) * T - cy) * z)
        im.alpha_composite(view, (VX, VY))

    def _draw_status(self, d):
        d.rectangle((0, H - STATUS_H, W, H), fill=(36, 44, 40, 255))
        pos = "palette tile %d" % self.pal_hover if self.pal_hover is not None else "(%d,%d) tile %d" % (self.cell + (self.doc.tile(*self.cell, self.layer),)) if self.cell else ""
        extra = "  object: " + self.obj_kind + " (N/C/B), double-click or Enter edits" if self.tool == "object" else ""
        d.text((6, H - STATUS_H + 3), "%s%s  %s  layer %d  zoom %dx  picked %dx%d  %s%s  %s" % (self.doc.name, "*" if self.doc.modified else "", self.tool, self.layer, self.zoom, self.pattern.w, self.pattern.h, pos, extra, self.msg), fill=(230, 230, 220, 255))


def _line(a, b):
    """The cells on the straight line from a to b (both included), so a fast mouse leaves no gaps."""
    (x0, y0), (x1, y1) = a, b; n = max(abs(x1 - x0), abs(y1 - y0)) or 1
    return [(x0 + round((x1 - x0) * i / n), y0 + round((y1 - y0) * i / n)) for i in range(n + 1)]


def _ints(v, *keys):
    try: [int(v[k]) for k in keys]; return all(0 <= int(v[k]) < 4096 for k in keys)
    except ValueError: return False


def main():
    import argparse, time
    ap = argparse.ArgumentParser(description="Build: level editor for .nw files"); ap.add_argument("level", nargs="?"); ap.add_argument("--dir"); ap.add_argument("--scale", type=float, default=1)
    a = ap.parse_args(); folder = a.dir or (os.path.dirname(os.path.abspath(a.level)) if a.level and os.path.exists(a.level) else None)
    ed = Editor(folder, a.level if a.level and os.path.exists(a.level) else None)
    if a.level and not os.path.exists(a.level): ed.open_doc(LevelDoc(os.path.basename(a.level)))
    win = window.Window("Graal Build", W, H, a.scale)
    import crashguard
    def loop():
        run = True
        while run:
            for ev in win.events():
                if ev[0] == "quit": run = False
                else: ed.mod = win.mod; ed.handle(ev)
            win.present(ed.draw().tobytes()); time.sleep(0.02)
    try: crashguard.run(loop)
    finally: win.close()


if __name__ == "__main__":
    main()
