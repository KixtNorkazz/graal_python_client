"""python3 test_leveldoc.py : the editable level (leveldoc.py): .nw read/write round trip, tile editing, fill, clipboard, objects, undo, saving."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import copy, os, random, tempfile
import config, leveldoc
from leveldoc import LevelDoc, Pattern, SIZE

def check(c, m):
    if not c: raise AssertionError(m)

def snapshot(d): return copy.deepcopy((d.tiles, d.links, d.signs, d.chests, d.baddies, d.npcs, d.layers))

def main():
    random.seed(7)
    d = LevelDoc("a.nw"); check(len(d.tiles) == 4096 and not d.modified, "a new level is empty and unmodified")
    d.begin(); d.paste(3, 4, Pattern(2, 2, [10, 11, 12, 13])); check(d.tile(3, 4) == 10 and d.tile(4, 5) == 13 and d.modified, "paste puts the pattern with its corner at (x, y)")
    n = d.paste(63, 63, Pattern(2, 2, [5, 5, 5, 5])); check(n == 1 and d.tile(63, 63) == 5, "what falls outside the level is cut off")
    check(d.copy_rect(3, 4, 2, 2).tiles == [10, 11, 12, 13] and d.copy_rect(-5, -5, 3, 3) is None and d.copy_rect(62, 62, 9, 9).w == 2, "copy_rect clips to the level")
    d.backtile = 7; check(d.clear_rect(3, 4, 2, 1) == 2 and d.tile(3, 4) == 7 and d.tile(4, 4) == 7 and d.tile(3, 5) == 12, "clear_rect uses the background tile")
    d.begin(); changed = d.fill(0, 0, Pattern.single(9)); check(changed == sum(1 for t in d.tiles if t == 9) and changed > 4000, "flood fill changes the connected area")
    check(d.tile(63, 63) == 5 and d.tile(3, 5) == 12 and d.tile(10, 10) == 9, "flood fill stops at other tiles")
    d2 = LevelDoc(); d2.fill(0, 0, Pattern(2, 1, [1, 2])); check(d2.tile(0, 0) == 1 and d2.tile(1, 0) == 2 and d2.tile(2, 0) == 1 and d2.tile(5, 9) in (1, 2), "fill repeats a pattern from the start tile")
    check(d2.fill(0, 0, Pattern.single(d2.tile(0, 0))) == 0, "filling with the same tile changes nothing")

    d3 = LevelDoc(); d3.paste(0, 0, Pattern.single(5)); before = snapshot(d3)
    d3.begin(); d3.paste(1, 1, Pattern.single(8)); d3.add_link("b.nw", 1, 2, 2, 1, "10", "20.5"); d3.add_sign(4, 5, "Hi\nthere\n"); d3.add_chest(6, 6, "bluerupee", 1); d3.add_baddy(7.5, 8, 4); d3.add_npc(9, 9.5, "door.png", "if (created) {\n  setshape 1,32,32;\n}")
    after = snapshot(d3); check(d3.signs[0]["text"] == "Hi\nthere", "trailing newlines of a sign are dropped")
    for _ in range(6): check(d3.undo(), "undo steps back")
    check(not d3.undo(), "undo past the start does nothing")
    check(snapshot(d3)[:6] == before[:6], "undo brings back the level as it was")
    while d3.redo(): pass
    check(snapshot(d3) == after, "redo brings the changes back")

    d3.edit("link", 0, level="c.nw"); d3.move("npc", 0, 1, -1); d3.move("chest", 0, 2, 0)
    check(d3.links[0]["level"] == "c.nw" and d3.npcs[0]["x"] == 10.0 and d3.npcs[0]["y"] == 8.5 and d3.chests[0]["x"] == 8, "edit and move objects")
    check(("chest", 0) in d3.objects_at(8, 6) and ("link", 0) in d3.objects_at(2, 2) and ("sign", 0) in d3.objects_at(4, 5) and ("baddy", 0) in d3.objects_at(7, 8) and ("npc", 0) in d3.objects_at(11, 9) and not d3.objects_at(30, 30), "objects_at finds what covers a tile")
    d3.remove("sign", 0); check(not d3.signs and d3.undo() and len(d3.signs) == 1, "remove and undo")

    text = d3.to_text(); back = LevelDoc.from_text(text, "x.nw")
    check(text.startswith("GLEVNW01\n") and snapshot(back) == snapshot(d3), "to_text / from_text round trip keeps tiles and every object")
    check("BADDY 7.5 8 4\n" in text and "BADDYEND" in text and "NPC door.png 10 8.5\n" in text and "CHEST 8 6 bluerupee 1" in text and "LINK c.nw 1 2 2 1 10 20.5" in text, "the records are written the way gs2emu writes them")
    layered = text.replace("LINK", "BOARD 5 6 3 1 AAABAC\nLINK", 1); lay = LevelDoc.from_text(layered)
    check(lay.tile(5, 6, 1) == 0 and lay.tile(6, 6, 1) == 1 and lay.tile(7, 6, 1) == 2 and lay.tile(4, 6, 1) == leveldoc.EMPTY and "BOARD 5 6 3 1 AAABAC" in lay.to_text() and lay.tile(5, 6) == d3.tile(5, 6), "a row of layer 1 is read, and written back as the same run")
    lay.begin(); lay.paste(10, 10, Pattern(2, 1, [7, 8]), 2); check(lay.tile(10, 10, 2) == 7 and lay.tile(10, 10) == d3.tile(10, 10) and lay.tile(12, 10, 2) == leveldoc.EMPTY, "a pattern pasted on layer 2 leaves layer 0 alone")
    check("BOARD 10 10 2 2 AHAI" in lay.to_text() and LevelDoc.from_text(lay.to_text()).tile(11, 10, 2) == 8, "layer 2 is written as a run of the set tiles and read back")
    lay.begin(); lay.clear_rect(10, 10, 2, 1, 2); check(lay.tile(10, 10, 2) == leveldoc.EMPTY and "BOARD 10 10" not in lay.to_text(), "clearing an upper layer empties it")
    lay.undo(); lay.undo(); check(lay.tile(10, 10, 2) == leveldoc.EMPTY and lay.layers.get(2) is None, "undo also covers the layers")

    with tempfile.TemporaryDirectory() as folder:
        p = os.path.join(folder, "mine.nw"); d3.save(p)
        check(os.path.exists(p) and not os.path.exists(p + ".part") and not d3.modified and d3.name == "mine.nw", "save writes the file atomically and clears the modified flag")
        check(snapshot(LevelDoc.load(p)) == snapshot(d3), "a saved level loads back the same")

    folders = [f for f in config.dirs("asset_dirs") if os.path.isdir(f)]; files = []
    for f in folders:
        files += [os.path.join(f, n) for n in sorted(os.listdir(f)) if n.lower().endswith(".nw")]
    random.shuffle(files); tested = 0
    for p in files[:150]:
        a = LevelDoc.load(p); b = LevelDoc.from_text(a.to_text())
        check(snapshot(a) == snapshot(b), f"real level {os.path.basename(p)} survives a write and read")
        tested += 1
    print(f"leveldoc tests passed ({tested} real levels round-tripped)")

main()
