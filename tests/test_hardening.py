"""python3 test_hardening.py : what a hostile game server must not be able to do: expand a compressed frame without limit, escape the GS1 expression evaluator, write outside the cache folder."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import bz2, os, tempfile, zlib
from PIL import Image
import graalproto, offline, weapons, filefetch

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    check(graalproto._inflate(zlib.decompressobj(), zlib.compress(b"a" * 5000)) == b"a" * 5000, "a normal zlib frame inflates")
    check(graalproto._inflate(bz2.BZ2Decompressor(), bz2.compress(b"a" * 5000)) == b"a" * 5000, "a normal bz2 frame inflates")
    for d, blob in ((zlib.decompressobj(), zlib.compress(b"\0" * (100 << 20))), (bz2.BZ2Decompressor(), bz2.compress(b"\0" * (100 << 20)))):
        try: graalproto._inflate(d, blob); raise AssertionError("a 100 MB frame was inflated")
        except ValueError: pass
    try: graalproto._inflate(zlib.decompressobj(), zlib.compress(b"a" * 5000)[:-6]); raise AssertionError("a truncated frame was accepted")
    except ValueError: pass

    S = offline.OfflineSession("turtlejunction-h4.nw", pos=(320, 416), account="TestA"); S.send = lambda l: None
    S.npcs[("p", 1)] = dict(IMAGE="a.gif", SCRIPT="", X2=320, Y2=320, LEVEL=S.level_name)
    cx = weapons.Ctx(S.npcrt.instance(("p", 1), S.npcs[("p", 1)]), S, "", "", ())
    marker = os.path.join(tempfile.gettempdir(), "graal_hardening_marker")
    if os.path.exists(marker): os.remove(marker)
    for e in ("().__class__.__base__.__subclasses__()", "strequals.__globals__['__builtins__']['__import__']('os').system('touch %s')" % marker, "(1).__class__"):
        check(weapons.evaluate(e, cx) == 0.0, f"attribute access in an expression is refused: {e}")
    check(not os.path.exists(marker), "no command was run")
    check(weapons.evaluate("1 + 2 == 3", cx), "ordinary expressions still work")
    import gs1, time as _time
    check(gs1._eval("().__class__.__base__.__subclasses__().__len__()", dict(x=0, y=0)) == 0.0, "the gs1 evaluator refuses attribute access too")
    for ev in (lambda e: gs1._eval(e.replace("^", "**"), dict(x=0, y=0)), lambda e: weapons.evaluate(e, cx)):
        t0 = _time.time(); ev("9^9^7")   # about 2 s as Python ints; 9^9^9 would take minutes
        check(_time.time() - t0 < 0.5, f"a huge power does not freeze the client: {_time.time() - t0:.1f}s")
        check(ev("1<<40") == 0.0 and ev("'ab'*3") == 0.0, "no shifts and no string repetition (1<<99999999999 or 'ab'*10^9 would allocate gigabytes)")
    check(weapons.evaluate("2^10", cx) == 1024 and weapons.evaluate("3*4-1", cx) == 11 and gs1._eval("x*3+y", dict(x=2, y=3)) == 9, "ordinary arithmetic is unchanged")

    with tempfile.TemporaryDirectory() as folder:
        class Sess: level_name = ""; gmap = ""
        f = filefetch.Fetcher(Sess(), folder)
        for bad in ("..", ".", "a/b.png", "..\\x.png"):
            f._store(bad.lower(), bad, b"x", 0)
        check(not os.listdir(folder) and not os.path.exists(os.path.join(folder, "..", "x.png")), f"names with path parts are not stored: {os.listdir(folder)}")
    # A picture that declares far more pixels than any real one (a few kB of PNG, hundreds of MB as RGBA) is refused, a big real one is not.
    import render, assets
    with tempfile.TemporaryDirectory() as folder:
        Image.new("1", (9000, 9000)).save(os.path.join(folder, "zz-bomb.png")); Image.new("1", (2534, 2345)).save(os.path.join(folder, "zz-real.png"))
        orig_find = assets.find; assets.find = lambda n, level=False, kind=None: os.path.join(folder, n) if os.path.exists(os.path.join(folder, n)) else orig_find(n, level)
        try: check(render.load_image("zz-bomb.png") is None and render.load_image("zz-real.png") is not None, "a picture bomb is refused, a real picture loads")
        finally: assets.find = orig_find
    # GS2 savestring / savelines: limited in size and number of files.
    import gs2src
    with tempfile.TemporaryDirectory() as folder:
        old_box = gs2src.SANDBOX; gs2src.SANDBOX = folder
        try:
            check(not gs2src.sandbox_write(os.path.join(folder, "big.txt"), "x" * (gs2src.SANDBOX_MAX_FILE + 1)), "a too big script file is refused")
            for i in range(gs2src.SANDBOX_MAX_FILES): gs2src.sandbox_write(os.path.join(folder, f"f{i}.txt"), "x")
            check(not gs2src.sandbox_write(os.path.join(folder, "one-more.txt"), "x") and gs2src.sandbox_write(os.path.join(folder, "f0.txt"), "y"), "no file past the count limit, existing ones can be rewritten")
        finally: gs2src.SANDBOX = old_box
    import gclient
    from graalproto import gchar, enc_pos
    sess = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(sess, "a", "b", "222", ("127.0.0.1", 1)); sess.send = lambda l: None
    sess.handle("pkt", 9, gchar(78) + enc_pos(480) + gchar(79) + enc_pos(488)); check(sess.pos == (480, 488), f"own X2/Y2 set the position: {sess.pos}")
    sess.pos = (480, 752); sess.handle("pkt", 9, gchar(25) + gchar(60)); check(sess.pos == (480, 752), f"an own prop without a position (AP counter) does not move the player back: {sess.pos}")
    sess.handle("pkt", 9, gchar(12) + gchar(2) + b"hi"); check(sess.pos == (480, 752), "nor does the chat text")
    sess.handle("pkt", 9, gchar(16) + gchar(20)); check(sess.pos == (480, 160), f"Y alone (20 half tiles = 160 px) moves only y: {sess.pos}")
    # Walking off the outer edge of a gmap: the server saves the cell as an unsigned byte (-1 -> 255) and the next login gets no level.
    rows = [["a%d.nw" % i for i in range(4)], ["b%d.nw" % i for i in range(4)]]
    for cell, pos, d, want in (((0, 0), (16, 280), "L", (0, 0)), ((0, 0), (500, 8), "U", (0, 0)), ((3, 0), (960, 280), "R", (3, 0)), ((1, 0), (16, 280), "L", (0, 0))):
        G = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(G, "a", "b", "222", ("127.0.0.1", 1)); G.send = lambda l: None
        G.gmap = "test.gmap"; G.gmap_rows = lambda: rows; G.ensure_neighbours = lambda: None; G.pos = pos
        G.me["GMAPLEVELX"], G.me["GMAPLEVELY"] = cell; G.map_cell = cell; G.level_name = rows[cell[1]][cell[0]]
        G.coll.blocked = lambda *a, **k: False; G.coll.rect_blocked = lambda *a, **k: False
        for i in range(6): G.step(d, i == 0, use_links=False)
        check(G.cell == want and -16 <= G.pos[0] <= 992 and -32 <= G.pos[1] <= 976, f"walking {d} from cell {cell} ends in {want}, leaning over an outer edge at most: {G.cell} {G.pos}")
    def gsess(cell, pos, gm_rows):
        G = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(G, "a", "b", "222", ("127.0.0.1", 1)); sent = []; G.send = sent.append
        G.gmap = "test.gmap"; G.gmap_rows = lambda: gm_rows; G.ensure_neighbours = lambda: None; G.me["GMAPLEVELX"], G.me["GMAPLEVELY"] = cell; G.map_cell = cell
        G.level_name = gm_rows[cell[1]][cell[0]] if gm_rows else None; G.pos = pos; G.coll.blocked = lambda *a, **k: False; G.coll.rect_blocked = lambda *a, **k: False
        return G, sent
    # At the outer edge of a gmap the player may lean over it as long as the wall box stays inside, like in Graal: gs2emu tests links at
    # (x+24, y+16) walking up, so a gate on row 0 needs y <= -1 to be reached.
    for cell, start, d, end in (((2, 1), (496, 904), "D", (496, 976)), ((2, 0), (280, 200), "U", (280, -32)), ((0, 0), (200, 504), "L", (-16, 504)), ((3, 0), (904, 504), "R", (992, 504))):
        G, sent = gsess(cell, start, rows)
        for i in range(150): G.step(d, i == 0, use_links=False)
        check(G.pos == end and G.cell == cell, f"walking {d} to the outer gmap edge from {cell} ends at {end}: {G.pos} {G.cell}")
        check(not any(b"\x2b\x1f" in l or b"\x2c\x1f" in l for l in sent), "no cell -1 is ever sent")
    # Before the map file has arrived (size unknown) crossing into a cell that is not negative works; a negative one never.
    G, sent = gsess((1, 0), (1000, 504), None)
    for i in range(4): G.step("R", i == 0, use_links=False)
    check(G.cell == (2, 0), f"an unknown-size gmap still lets the player cross to the right: {G.cell} {G.pos}")
    G, sent = gsess((0, 0), (16, 504), None)
    for i in range(10): G.step("L", i == 0, use_links=False)
    check(G.cell == (0, 0) and not any(b"\x2b\x1f" in l for l in sent), f"but never to cell -1: {G.cell} {G.pos}")
    # A plain level: an edge link along any side is reached by walking into it (the collision code decides how far, not the gmap rule).
    for d, start, lk in (("D", (496, 904), ["south.nw", "0", "63", "64", "1", "playerx", "0"]), ("U", (496, 104), ["north.nw", "0", "0", "64", "1", "playerx", "61"]),
                         ("L", (104, 504), ["west.nw", "0", "0", "1", "64", "61", "playery"]), ("R", (904, 504), ["east.nw", "63", "0", "1", "64", "0", "playery"])):
        G = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(G, "a", "b", "222", ("127.0.0.1", 1)); sent = []; G.send = sent.append
        G.level_name = "here.nw"; G.levels["here.nw"] = gclient.Level("here.nw"); G.levels["here.nw"].links = [lk]
        G.coll.blocked = lambda *a, **k: False; G.coll.rect_blocked = lambda *a, **k: False; G.pos = start
        took = None
        for i in range(120):
            took = G.step(d, i == 0)
            if took: break
        check(took is not None and took["level"] == lk[0], f"the edge link walking {d} is taken: {G.pos}")
        check(not any(b"\x2b" in l and b"\x2c" in l for l in sent), "a plain level never sends a gmap cell")
    # An NPC props packet that ends inside a prop keeps what was read (the frost trees lost picture and script).
    from graalproto import gint_enc
    T = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(T, "a", "b", "222", ("127.0.0.1", 1)); T.send = lambda l: None
    T.handle("line", 3, gint_enc(1169, 3) + gchar(0) + gchar(18) + b"val_frost-tree.png" + gchar(1) + gint_enc(5, 2) + b"hello" + gchar(2))
    check(T.npcs.get(1169) == {"IMAGE": "val_frost-tree.png", "SCRIPT": "hello"}, f"a truncated NPC packet keeps its props: {T.npcs.get(1169)}")
    # playershootssword reaches the selected weapon (and weapons that cannot be selected), not every weapon: the dragon weapons share client.dragon.
    D = offline.OfflineSession("turtlejunction-h4.nw", pos=(320, 416), account="TestA"); D.send = lambda l: None
    mk = lambda ani: "//#CLIENTSIDE\nif (weaponfired) { setstring client.dragon,1; }\nif (playershootssword) { if (strtofloat(#s(client.dragon)) == 1) setani %s,; }\n" % ani
    D.runner.add("Green", "", mk("green-fire")); D.runner.add("Undead", "", mk("undead-fire")); D.runner.add("-passive", "", "//#CLIENTSIDE\nif (playershootssword) { this.hit = 1; }\n")
    from inventory import Inventory
    inv = Inventory(); inv.choose(D, [w.name for w in D.runner.firable()].index("Green")); inv.fire(D); D.tick_all(); D.attack(); D.tick_all()
    check(D.me.get("GANI") == "green-fire", f"the selected dragon answers the sword, the other does not: {D.me.get('GANI')}")
    print("hardening tests passed")

main()
