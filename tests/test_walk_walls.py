"""python3 test_walk_walls.py : a player put inside a wall can walk out of it (13 of 43 links into the worldmap drop you with the feet on a
wall tile), but never deeper or along it; and a step blocked by a wall slides half a step sideways into a one-tile gap, like Graal."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import gclient
from graalproto import gchar, enc_pos

def check(c, m):
    if not c: raise AssertionError(m)

def session(walls, pos):
    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = sent.append
    s.level_name = "here.nw"; s.pos = pos
    s.coll.tile_blocked = lambda s_, gx, gy, rows: (gx, gy) in walls or not (0 <= gx < 64 and 0 <= gy < 64)
    return s, sent

def walk(s, d, n):
    for i in range(n): s.step(d, i == 0, use_links=False)
    return s.pos

def main():
    # The worldmap_b5 teleporter: feet (row 41) on a wall row, open above.
    walls = {(x, 41) for x in range(64)} | {(x, 42) for x in range(64)}
    s, sent = session(walls, (192, 624))
    check(s.coll.wall_overlap(s, *s.pos) > 0, "the start overlaps the wall")
    check(walk(s, "U", 4) == (192, 592), f"out of it: {s.pos}")
    check(walk(s, "D", 4) == (192, 608), f"and then not back in: {s.pos}")
    # Deep inside a thick wall (the portwolfe doors): no single step lowers the overlap, but the player can still walk out.
    walls = {(x, y) for x in range(64) for y in range(35, 45)}
    s, _ = session(walls, (680, 624))
    check(walk(s, "U", 40)[1] <= 35 * 16 - 48, f"walks out of a wall it was put deep inside: {s.pos}")
    check(walk(s, "D", 4)[1] <= 35 * 16 - 32, f"and does not walk back in: {s.pos}")
    check(any(gchar(79) + enc_pos(592) in l for l in sent), "the server is told the new Y")
    # A one-tile corridor going up (column 10) from an open row; the player stands half a tile to the left of it.
    walls = {(x, y) for y in range(10, 30) for x in range(64) if x != 10}
    s, sent = session(walls, (136, 30 * 16 - 32 + 64))   # box (x+16..x+32) covers columns 9.5..10.5
    walk(s, "U", 12)
    check(s.pos[0] == 144 and s.pos[1] < 30 * 16 - 32, f"the player slid into the corridor and went up it: {s.pos}")
    check(any(gchar(78) + enc_pos(144) in l for l in sent), "the sideways slide is sent as X2")
    # No slide through a wall: a closed wall row with no gap.
    walls = {(x, 20) for x in range(64)}
    s, _ = session(walls, (136, 20 * 16 - 32 + 32))
    check(walk(s, "U", 8)[0] == 136, f"no gap, no sideways slide: {s.pos}")
    # A script that sets playerx / playery (Click Warp: playerx = mousex) moves like a step: into the next gmap cell, never past the map, told to the server.
    rows = [["a%d.nw" % i for i in range(4)], ["b%d.nw" % i for i in range(4)]]
    def gsess(cell):
        g = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(g, "a", "b", "222", ("127.0.0.1", 1)); out = []; g.send = out.append
        g.gmap = "t.gmap"; g.gmap_rows = lambda: rows; g.ensure_neighbours = lambda: None; g.me["GMAPLEVELX"], g.me["GMAPLEVELY"] = cell; g.map_cell = cell; g.level_name = rows[cell[1]][cell[0]]
        return g, out
    g, out = gsess((1, 0)); g.pos = (1100, 300); g.moved_by_script(); check(g.cell == (2, 0) and g.pos == (76, 300) and out, f"a click in the next cell moves there: {g.cell} {g.pos}")
    g, out = gsess((0, 0)); g.pos = (-300, 300); g.moved_by_script(); check(g.cell == (0, 0) and g.pos == (0, 300) and out[-1] == gclient.gline(2, gchar(78) + enc_pos(0) + gchar(79) + enc_pos(300)), f"a click past the edge stays in the map: {g.pos}")
    g, out = gsess((1, 0)); g.pos = (500, 600); g.moved_by_script(); check(out[-1] == gclient.gline(2, gchar(78) + enc_pos(500) + gchar(79) + enc_pos(600)), "the server is told both coordinates")
    print("walk walls tests passed")

main()
