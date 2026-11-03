"""python3 test_editor.py : the level editor driven by synthetic mouse and key events: palette, painting, fill, selection, clipboard, objects, links, signs, dialogs, saving."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import os, socket, tempfile
from PIL import Image

def _no_network(*a, **k): raise AssertionError("Build must not use the network")
socket.socket = _no_network
import editor, window
from buildlib import Library
from filebrowser import FileBrowser
from editor import Editor, VX, VY, T, TOOLBAR_H, W, H, PAL_Y, PAL_W
from leveldoc import LevelDoc, EMPTY

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    folder = tempfile.mkdtemp(); ed = Editor(folder, library=Library(tempfile.mkdtemp()))
    def cell(tx, ty): return (VX + (tx * T - ed.cam[0]) * ed.zoom + 8 * ed.zoom, VY + (ty * T - ed.cam[1]) * ed.zoom + 8 * ed.zoom)
    def pal(c, r): return (8 + c * T + 8, PAL_Y + r * T + 8)
    def click(x, y, b=1): ed.handle(("mousedown", b, x, y)); ed.handle(("mouseup", b, x, y))
    def drag(a, b, btn=1, steps=()):
        ed.handle(("mousedown", btn, *a))
        for s in steps: ed.handle(("mousemove", *s))
        ed.handle(("mousemove", *b)); ed.handle(("mouseup", btn, *b))
    def key(ch, ctrl=False, shift=False):
        ed.mod = (window.KMOD_CTRL if ctrl else 0) | (window.KMOD_SHIFT if shift else 0); ed.handle(("down", ord(ch) if isinstance(ch, str) else ch)); ed.mod = 0
    def typed(text):
        for ch in text: ed.handle(("text", ch))
    def enter(ctrl=False):
        ed.mod = window.KMOD_CTRL if ctrl else 0; ed.handle(("down", window.K_RETURN)); ed.mod = 0

    im = ed.draw(); check(im.size == (W, H), "the editor draws a full frame")
    check(ed.tool == "select", "Build starts with the select tool"); key("t")

    drag(pal(2, 1), pal(3, 2)); check((ed.pattern.w, ed.pattern.h) == (2, 2) and ed.pattern.tiles == [18, 19, 34, 35], f"dragging in the palette picks a tile rectangle: {ed.pattern.tiles}")
    click(*pal(5, 0)); check(ed.pattern.tiles == [5], "a click in the palette picks one tile")
    drag(cell(1, 1), cell(5, 1), steps=[cell(2, 1), cell(3, 1), cell(4, 1)])
    check(all(ed.doc.tile(x, 1) == 5 for x in range(1, 6)) and ed.doc.tile(6, 1) == 0 and ed.doc.modified, "dragging with the tile tool paints a line")
    drag(cell(1, 3), cell(9, 6)); check(all(ed.doc.tile(1 + round(8 * i / 8), 3 + round(3 * i / 8)) == 5 for i in range(9)) and ed.doc.tile(5, 5) == 5, "a fast mouse movement leaves no gaps in the line")
    key("z", ctrl=True); key("z", ctrl=True); check(all(ed.doc.tile(x, 1) == 0 for x in range(1, 6)), "one undo takes back the whole stroke")
    key("y", ctrl=True); key("y", ctrl=True); check(ed.doc.tile(3, 1) == 5, "redo paints it again")

    drag(pal(2, 1), pal(3, 2)); click(*cell(10, 10)); check([ed.doc.tile(10, 10), ed.doc.tile(11, 10), ed.doc.tile(10, 11), ed.doc.tile(11, 11)] == [18, 19, 34, 35], "a click stamps the picked rectangle")
    drag(cell(10, 20), cell(12, 21), btn=3); check(ed.pattern.w == 3 and ed.pattern.h == 2, "the right button drag picks tiles from the level")
    key("f"); click(*cell(30, 30)); check(ed.doc.tile(40, 50) == ed.pattern.at(10, 20) and ed.doc.tile(30, 30) == ed.pattern.tiles[0], "the fill tool floods the area")

    key("s"); drag(cell(10, 10), cell(11, 11)); check(ed.sel == (10, 10, 2, 2), f"the select tool makes a rectangle: {ed.sel}")
    key("c", ctrl=True); check(ed.clip.tiles == [18, 19, 34, 35], "Ctrl+C copies the selection")
    key("v", ctrl=True); click(*cell(20, 5)); check(ed.doc.tile(20, 5) == 18 and ed.doc.tile(21, 6) == 35 and not ed.pasting, "Ctrl+V then a click pastes")
    check(ed.sel == (20, 5, 2, 2), "the pasted tiles become the selection")
    key("x", ctrl=True); check(ed.doc.tile(20, 5) == ed.doc.backtile, "Ctrl+X cuts the selection")
    key("z", ctrl=True); check(ed.doc.tile(20, 5) == 18, "and undo puts it back")
    drag(cell(10, 10), cell(11, 11)); key(editor.K_DELETE); check(ed.doc.tile(11, 11) == ed.doc.backtile, "Delete clears the selection")

    key("o"); key("c"); click(*cell(8, 8)); check(ed.modal is not None and len(ed.doc.chests) == 1, "a click with the object tool opens the chest dialog")
    typed(""); ed.modal.fields[0].value = "bluerupee"; enter(); check(ed.modal is None and ed.doc.chests[0]["item"] == "bluerupee", "OK stores the chest")
    key("c"); click(*cell(9, 9)); ed.modal.fields[0].value = "nonsense"; enter(); check(ed.modal is not None and ed.modal.error, "a wrong item is refused with a message")
    ed.handle(("down", window.K_ESCAPE)); check(ed.modal is None and len(ed.doc.chests) == 1, "Esc cancels and the new chest is gone again")
    key("b"); click(*cell(12, 12)); ed.modal.fields[0].value = "4"; ed.modal.fields[1].value = "Argh"; enter(); check(ed.doc.baddies[0]["type"] == 4 and ed.doc.baddies[0]["verses"][0] == "Argh", "baddy type and verses")
    key("n"); click(*cell(15, 15)); ed.modal.fields[0].value = "door.png"; ed.modal.focus = 1; typed("if (created) {"); enter(); typed("}"); enter(ctrl=True)
    check(ed.doc.npcs[0]["image"] == "door.png" and ed.doc.npcs[0]["script"] == "if (created) {\n}" and ed.doc.npcs[0]["x"] == 15.0, f"NPC image and a two line script: {ed.doc.npcs}")
    ed.handle(("mousedown", 1, *cell(15, 15))); ed.handle(("mousemove", *cell(18, 17))); ed.handle(("mouseup", 1, *cell(18, 17)))
    check(ed.doc.npcs[0]["x"] == 18.0 and ed.doc.npcs[0]["y"] == 17.0, "dragging an object moves it")
    n_undo = len(ed.doc._undo); key("z", ctrl=True); check(ed.doc.npcs[0]["x"] == 15.0, "the whole drag is one undo step")
    ed.handle(("mousedown", 1, *cell(15, 15))); ed.handle(("mouseup", 1, *cell(15, 15))); key(editor.K_DELETE); check(not ed.doc.npcs, "Delete removes the selected object")

    for n_ in list(ed.doc.npcs): ed.doc.npcs.remove(n_)
    key("l"); drag(cell(20, 20), cell(21, 20)); check(ed.modal is not None and ed.doc.links[0]["w"] == 2 and ed.doc.links[0]["h"] == 1, "dragging with the link tool opens the link dialog")
    ed.modal.fields[0].value = ""; enter(); check(ed.modal.error, "a link needs a level name")
    ed.modal.fields[0].value = "other.nw"; ed.modal.fields[6].value = "12.5"; enter()
    check(ed.doc.links[0]["level"] == "other.nw" and ed.doc.links[0]["ny"] == "12.5" and ed.doc.links[0]["x"] == 20, "link stored")
    key("i"); click(*cell(25, 25)); ed.modal.fields[0].value = "Hello"; typed(" world"); enter(ctrl=True); check(ed.doc.signs[0]["text"] == "Hello world" and (ed.doc.signs[0]["x"], ed.doc.signs[0]["y"]) == (25, 25), "a sign")
    click(*cell(25, 25)); ed.handle(("down", 0x4000003A)); check(not ed.doc.signs and ed.modal is None, "F1 in the sign dialog deletes the sign")
    check(ed.draw().size == (W, H), "drawing with every kind of object works")

    ed.scroll(5000, 5000); check(ed.cam == [1024 - editor.VW, 1024 - editor.VH], "scrolling stops at the edge of the level"); ed.scroll(-5000, -5000)

    key("+"); check(ed.zoom == 2 and ed.cell_at(*cell(7, 9)) == (7, 9), "zoom 2x: a click still lands on the tile under it"); key("t"); click(*cell(7, 9)); check(ed.doc.tile(7, 9) == ed.pattern.tiles[0], "painting while zoomed"); ed.draw()
    ed.scroll(5000, 5000); check(ed.cam == [1024 - editor.VW // 2, 1024 - editor.VH // 2], "zoomed scrolling stops at the edge"); ed.scroll(-5000, -5000); key("-"); check(ed.zoom == 1, "zoom back")

    click(*pal(7, 0)); key("t"); key("]"); key("]"); check(ed.layer == 2, "] goes up a layer"); click(*cell(35, 30)); check(ed.doc.tile(35, 30, 2) == 7 and ed.doc.tile(35, 30) != 7 and ed.doc.layers.keys() == {2}, "painting on layer 2 leaves layer 0")
    drag(cell(35, 30), cell(36, 30), btn=3); check(ed.pattern.tiles[0] == 7, "picking reads the current layer"); key("s"); drag(cell(35, 30), cell(35, 30)); key(editor.K_DELETE); check(ed.doc.tile(35, 30, 2) == EMPTY and ed.doc.tile(35, 30) != 7, "Delete empties the tile on an upper layer")
    key("t"); click(*cell(35, 30)); ed.draw(); key("["); key("["); key("["); check(ed.layer == 0, "[ goes down, but not below 0"); ed.doc.set_tile(35, 30, EMPTY, 2); ed.refresh_all()

    drag(pal(2, 1), pal(3, 2)); key("b", ctrl=True); check(len(ed.lib.objects) == 1 and ed.lib.objects[0]["tiles"] == [18, 19, 34, 35], "Ctrl+B saves the picked tiles as an object")
    key(9); check(ed.pal_mode == "objects" and ed.draw().size == (W, H), "Tab shows the saved objects")
    click(*pal(5, 0)); ed.pal_mode = "objects"; click(8 + 4, PAL_Y + 4); check(ed.pal_item == 0 and ed.pattern.tiles == [18, 19, 34, 35], "clicking an object picks it")
    key("t"); click(*cell(33, 32)); check(ed.doc.tile(34, 33) == 35, "the object is stamped like picked tiles")
    key(editor.K_DELETE); check(not ed.lib.objects and ed.pal_item is None, "Delete removes the object from the library")
    key("o"); key("n"); click(*cell(30, 34)); ed.modal.fields[0].value = "tpl.png"; ed.modal.fields[1].value = "if (created) { setshape 1,32,32; }"; enter(ctrl=True)
    key("b", ctrl=True, shift=True); ed.modal.fields[0].value = "block"; enter(); check(ed.lib.npc_names() == ["block"] and ed.lib.npc("block") == ("tpl.png", "if (created) { setshape 1,32,32; }"), "Ctrl+Shift+B saves the selected NPC as a template")
    key(9); check(ed.pal_mode == "npcs", "Tab goes on to the NPC templates"); click(12, PAL_Y + 4); check(ed.npc_template == "block" and ed.tool == "object", "picking a template makes new NPCs use it")
    click(*cell(30, 36)); ed.modal.fields[0].value; enter(); check(ed.doc.npcs[-1]["image"] == "tpl.png" and "setshape" in ed.doc.npcs[-1]["script"] and ed.doc.npcs[-1]["y"] == 36.0, f"a new NPC starts from the template: {ed.doc.npcs[-1]}")
    key(9); check(ed.pal_mode == "tiles", "Tab goes round to the tiles"); ed.draw()
    ed.handle(("wheel", 1)); ed.handle(("down", window.K_LEFT)); ed.handle(("down", editor.K_F2)); ed.handle(("down", editor.K_PGDN)); ed.draw()

    key("s", ctrl=True); check(isinstance(ed.modal, FileBrowser) and ed.modal.save, "saving an untitled level opens the file browser")
    typed("mine"); ed.draw(); enter(); p = os.path.join(folder, "mine.nw")
    check(os.path.exists(p) and ed.doc.name == "mine.nw" and not ed.doc.modified, "saved under that name with .nw added")
    saved = LevelDoc.load(p); check(saved.tiles == ed.doc.tiles and len(saved.links) == 1 and len(saved.baddies) == 1 and len(saved.chests) == 1, "the file has what the editor shows")
    ed.handle(("down", ord("k"))); key("s", ctrl=True); check(ed.modal is None, "Ctrl+S on a named level saves without asking")
    def side(label): return next((W - 40, y + 4) for y, k, l, a in ed.side_buttons() if l == label)
    ed.draw(); click(*side("Save")); check(isinstance(ed.modal, FileBrowser) and ed.modal.text == "mine.nw", "the side Save button always opens the browser, with the name filled in")
    ed.handle(("down", window.K_ESCAPE)); check(ed.modal is None, "Esc closes the browser")
    key("n", ctrl=True); check(ed.modal is not None and ed.modal.fields[0].key == "name", "new level (nothing unsaved) asks for a name")
    ed.modal.fields[0].value = "fresh.nw"; enter(); check(ed.doc.name == "fresh.nw" and not any(ed.doc.tiles), "a new level is empty")
    sub = os.path.join(folder, "maps"); os.makedirs(sub); LevelDoc("deep.nw").save(os.path.join(sub, "deep.nw"))
    key("o", ctrl=True); check(isinstance(ed.modal, FileBrowser) and [r[1] for r in ed.modal.rows] == ["..", "maps", "mine.nw"] or [r[1] for r in ed.modal.rows][1:] == ["maps", "mine.nw"], f"open lists folders and the .nw files: {[r[1] for r in ed.modal.rows]}")
    ed.draw(); typed("min"); enter(); check(ed.doc.name == "mine.nw" and len(ed.doc.links) == 1, "type to filter, Enter opens")
    key("o", ctrl=True); typed("maps"); enter(); check(ed.modal is not None and ed.modal.folder == sub, "Enter on a folder goes into it"); enter()
    check(ed.doc.name == "deep.nw" and ed.dir == sub, "opening from another folder makes that the working folder")
    key("s", ctrl=True, shift=True); ed.modal.text = ""; typed("copy"); ed.handle(("down", window.K_RETURN)); check(os.path.exists(os.path.join(sub, "copy.nw")), "Save as writes to the browsed folder")
    ed.dir = folder
    ed.doc.begin(); key("n", ctrl=True); check(ed.modal.fields[0].key == "answer", "unsaved changes are asked about before a new level")
    ed.handle(("down", window.K_ESCAPE)); check(ed.doc.name == "copy.nw", "Esc keeps working on the level")
    for dlg in (ed.draw,): dlg()

    ed2 = Editor(tempfile.mkdtemp(), library=Library(tempfile.mkdtemp())); ed = ed2; ed.mouse = (40, 100)
    check(ed.tile_number(0, 0) == 0 and ed.tile_number(17, 2) == 512 + 32 + 1 and ed.tile_number(127, 31) == 7 * 512 + 31 * 16 + 15, "palette columns map onto tile numbers across the whole tileset")
    ed.handle(("wheel", -1)); check(ed.pal_x == 4, "the wheel over the palette scrolls it sideways"); ed.handle(("wheel", 1)); ed.handle(("wheel", 1)); check(ed.pal_x == 0, "and stops at the left edge")
    ed.handle(("down", editor.K_PGDN)); check(ed.pal_x == 16, "PgDn moves a screen of tiles"); ed.pal_x = 200 and 112; ed.scroll_palette(50); check(ed.pal_x == 112, "stops at the right edge"); ed.pal_x = 0
    click(8 + 128, PAL_Y + 520); check(ed.pal_x == 56, f"clicking the scroll bar jumps there: {ed.pal_x}"); ed.handle(("mousedown", 1, 8 + 20, PAL_Y + 520)); ed.handle(("mousemove", 8 + 200, PAL_Y + 520)); ed.handle(("mouseup", 1, 8 + 200, PAL_Y + 520)); check(ed.pal_x > 80, "dragging the bar scrolls")
    ed.pal_x = 16; click(*pal(2, 1)); check(ed.pattern.tiles == [512 + 16 + 2], f"a click in a scrolled palette picks from the right page: {ed.pattern.tiles}")
    ed.pal_x = 14; drag(pal(0, 0), pal(3, 0)); check(ed.pattern.tiles == [14, 15, 512, 513], f"a drag across a page edge picks tiles by position: {ed.pattern.tiles}")
    ed.pal_x = 0; ed.handle(("mousedown", 1, *pal(10, 0))); ed.handle(("mousemove", PAL_W - 4, PAL_Y + 8)); check(ed.pal_x >= 1, "dragging to the edge scrolls the palette along"); ed.handle(("mouseup", 1, PAL_W - 4, PAL_Y + 8)); ed.pal_x = 0
    ed.mouse = (500, 300); ed.handle(("wheel", 1)); check(ed.cam[1] == 0, "the wheel over the level still scrolls the level"); ed.draw()

    TS = os.path.join(tempfile.mkdtemp(), "my_tiles.png"); Image.new("RGBA", (512, 512), (200, 30, 30, 255)).save(TS)
    import assets; assets.index()["my_tiles.png"] = TS
    ed.draw(); click(PAL_W - 40, TOOLBAR_H + 30); check(isinstance(ed.modal, FileBrowser) and ed.modal.preview, "the Tileset button opens an image picker")
    typed("my_t"); ed.draw(); enter(); check(ed.base == "my_tiles.png" and ed.lib.setting("tileset") == "my_tiles.png" and ed.tileset.getpixel((5, 5))[:3] == (200, 30, 30), "choosing an image makes it the tileset and remembers it")
    check(Editor(tempfile.mkdtemp(), library=ed.lib).base == "my_tiles.png", "the next session starts with the same tileset")
    ed.draw(); ed.pal_mode = "npcs"; click(PAL_W - 40, TOOLBAR_H + 30); typed("my_t"); enter(); check(ed.npc_image == "my_tiles.png" and ed.tool == "object", "the Image button in the NPC palette sets the picture for new NPCs")
    key("n"); click(*cell(5, 5)); check(ed.modal.fields[0].value == "my_tiles.png", "a new NPC starts with that picture"); ed.modal.fields[1].value = "if (created) {}"
    ed.handle(("down", 0x4000003A + 3)); check(isinstance(ed.modal, FileBrowser) and ed.modal.flat, "F4 in the NPC dialog lists the example scripts")
    typed("Warp"); enter(); check(ed.modal.fields[0].value == "my_tiles.png" and "setlevel2" in ed.modal.fields[1].value and ed.modal.fields[1].value.startswith("if (created) {}"), f"the example is added to the script: {ed.modal.fields[1].value!r}")
    scr = os.path.join(tempfile.mkdtemp(), "hi.txt"); open(scr, "w").write("if (playerenters) {\n}\n")
    ed.handle(("down", 0x4000003A + 2)); ed.modal.text = ""; ed.modal.folder = os.path.dirname(scr); ed.modal._refresh(); enter(); check("playerenters" in ed.modal.fields[1].value and "setlevel2" not in ed.modal.fields[1].value, "F3 loads a script from a file")
    enter(ctrl=True); check(ed.modal is None and ed.doc.npcs[-1]["image"] == "my_tiles.png" and "playerenters" in ed.doc.npcs[-1]["script"], "OK stores the NPC")
    click(*cell(5, 5)); click(*cell(5, 5)); check(ed.modal is not None and ed.modal.fields[0].key == "image", "a double-click on an NPC opens its dialog"); ed.handle(("down", window.K_ESCAPE)); ed.draw()
    n0 = len(ed.doc.npcs); ed.handle(("mousedown", 1, *side("Character"))); check(ed.drag_new is not None and len(ed.doc.npcs) == n0, "pressing the Character button only picks it up")
    ed.handle(("mousemove", *cell(20, 28))); ed.draw(); ed.handle(("mouseup", 1, *cell(20, 28))); n = ed.doc.npcs[-1]
    check(len(ed.doc.npcs) == n0 + 1 and ed.modal is None and (n["x"], n["y"]) == (20.0, 28.0), "dragging it onto the level drops one character, without a dialog")
    check("showcharacter" in n["script"] and "setcharprop #3,val-hellsinging-dalmarguard.gif" in n["script"] and "setcharprop #8,hellsinging-dalmarguardbody.gif" in n["script"] and "shieldpower = 1;" in n["script"], "with the quick character script")
    key("t"); click(*cell(22, 28)); check(len(ed.doc.npcs) == n0 + 1 and ed.modal is None, "clicking the level with the tile tool places no NPC"); ed.draw()
    ed.handle(("mousedown", 1, *side("Empty NPC"))); ed.handle(("mouseup", 1, *cell(24, 28))); check(ed.modal is not None and ed.modal.fields[1].value == "" and len(ed.doc.npcs) == n0 + 2, "an empty NPC opens its code window")
    typed("if (created) {}"); ed.modal.focus = 1; enter(ctrl=True); check(ed.doc.npcs[-1]["x"] == 24.0, "kept")
    ed.handle(("mousedown", 1, *side("Character"))); ed.handle(("mouseup", 1, PAL_W - 50, 300)); check(len(ed.doc.npcs) == n0 + 2, "letting go outside the level drops nothing")
    ed.draw()

    ed3 = Editor(tempfile.mkdtemp(), library=Library(tempfile.mkdtemp())); ed = ed3
    for y in range(4, 7):
        for x in range(4, 8): ed.doc.set_tile(x, y, 100 + x)
    ed.doc.add_npc(5, 5, "-", "// n"); ed.doc.add_chest(6, 4); ed.doc.add_link("a.nw", 4, 6, 2, 1, "1", "1"); ed.doc.add_sign(30, 30, "far"); ed.refresh_all()
    drag(cell(4, 4), cell(7, 6)); check(ed.sel == (4, 4, 4, 3), f"a left drag with the select tool marks a rectangle: {ed.sel}")
    ed.handle(("mousedown", 1, *cell(5, 5))); ed.handle(("mousemove", *cell(6, 5))); ed.draw(); ed.handle(("mousemove", *cell(15, 9))); ed.draw()
    check(ed.moving is not None and ed.doc.tile(4, 4) == ed.doc.backtile, "dragging inside the selection lifts it")
    ed.handle(("mouseup", 1, *cell(15, 9)))
    check(ed.moving is None and ed.sel == (14, 8, 4, 3) and ed.doc.tile(14, 8) == 104 and ed.doc.tile(17, 10) == 107 and ed.doc.tile(4, 4) == ed.doc.backtile, f"and drops the tiles where the mouse lets go: {ed.sel}")
    check(ed.doc.npcs[0]["x"] == 15.0 and ed.doc.npcs[0]["y"] == 9.0 and (ed.doc.chests[0]["x"], ed.doc.chests[0]["y"]) == (16, 8) and (ed.doc.links[0]["x"], ed.doc.links[0]["y"]) == (14, 10) and ed.doc.signs[0]["x"] == 30,
          "the NPC, chest and link inside move with it, the sign outside stays")
    key("z", ctrl=True); check(ed.doc.tile(4, 4) == 104 and ed.doc.npcs[0]["x"] == 5.0 and ed.doc.chests[0]["x"] == 6, "one undo takes the whole move back"); key("y", ctrl=True)
    ed.handle(("mousedown", 1, *cell(15, 9))); ed.handle(("mouseup", 1, *cell(15, 9))); check(ed.sel == (14, 8, 4, 3) and ed.doc.tile(14, 8) == 104, "a click inside the selection without moving changes nothing")
    ed.handle(("mousedown", 1, *cell(15, 9))); ed.handle(("mousemove", *cell(0, 0))); ed.handle(("mouseup", 1, *cell(0, 0))); check(ed.sel[:2] == (0, 0), f"a move stops at the edge of the level: {ed.sel}")
    key("c", ctrl=True); check(len(ed.clip_objs) == 3, f"Ctrl+C copies the tiles and the objects: {ed.clip_objs}")
    key("p", ctrl=True); check(ed.pasting, "Ctrl+P pastes as well as Ctrl+V"); ed.draw(); click(*cell(20, 20))
    check(ed.doc.tile(20, 20) == 104 and len(ed.doc.npcs) == 2 and ed.doc.npcs[1]["x"] == 21.0 and len(ed.doc.chests) == 2 and len(ed.doc.links) == 2 and ed.sel == (20, 20, 4, 3), "the copy lands with its objects")
    key(editor.K_DELETE); check(ed.doc.tile(20, 20) == ed.doc.backtile and len(ed.doc.npcs) == 1 and len(ed.doc.links) == 1, "Delete clears the tiles and the objects of the selection")
    drag(cell(0, 0), cell(3, 2)); key("x", ctrl=True); check(not ed.doc.npcs and not ed.doc.chests and len(ed.doc.signs) == 1, "Ctrl+X takes the objects away too")
    for k_ in (window.K_DOWN, window.K_DOWN): ed.handle(("repeat", k_))
    check(ed.cam[1] == 128, f"held arrow keys repeat: {ed.cam}")
    key("o"); key("n"); click(*cell(10, 10)); f = ed.modal.fields[0]; f.value = "abcdef"
    for _ in range(3): ed.handle(("repeat", window.K_LEFT))
    ed.handle(("repeat", window.K_BACKSPACE)); check(f.value == "abdef" and f.pos == 2, f"a held key keeps moving the text cursor and deleting: {f.value!r} {f.pos}")
    ed.handle(("repeat", window.K_RETURN)); check(ed.modal is not None, "Enter does not repeat")
    ed.handle(("down", window.K_ESCAPE))
    print("editor tests passed")

main()
