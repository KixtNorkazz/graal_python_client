"""python3 test_ladder.py : climbing a ladder (the world_ladder class). A script that moves the player (player.y in GS2, playery in GS1) takes a
link the player lands on, as Graal does - the ladder in echobaseint_guardhouse leads up into the link to echobase_a2 - and the walk gani the
ladder set ends there instead of playing on the spot in the next level."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import gclient

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = lambda l: sent.append(bytes(l))
    lv = gclient.Level("zz_house.nw"); lv.board = bytes(8192); lv.links = [("zz_roof.nw", "24", "22", "2", "1", "33", "36")]
    s.levels["zz_house.nw"] = lv; s.level_name = "zz_house.nw"; s.gmap = None; s.pos = (376, 432)
    warps = []; s.warp = lambda level, x, y: warps.append((level, x, y))
    s.play_gani("walk")   # the ladder's setani("walk", null)
    import time; s.weapon_ani_until = 0.0
    def set_y(v):
        s.pos = (s.pos[0], int(v * 16)); s.moved_by_script()
    set_y(26.0); check(not warps, "moving along the ladder below the link: no warp")
    set_y(21.0); check(warps and warps[-1][0] == "zz_roof.nw", f"the script put the player on the link: it is taken ({warps})")
    check(s.me["GANI"] == "idle", f"the ladder's walk ends at the link: {s.me.get('GANI')}")
    # The ladder class (laboo1 and 73 more levels): attachplayertoobj on touch, then onTimeout climbs while playerattached is true.
    t = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(t, "a", "b", "222", ("127.0.0.1", 1)); t.send = lambda l: None
    lv2 = gclient.Level("zz_cliff.nw"); lv2.board = bytes(8192); t.levels["zz_cliff.nw"] = lv2; t.level_name = "zz_cliff.nw"; t.gmap = None
    lad = "//#CLIENTSIDE\nfunction onCreated() {\n  setshape(1, 32, 64);\n}\nfunction onPlayerTouchsMe() {\n  attachplayertoobj(0, id);\n}"
    t.npcs[1] = dict(IMAGE="ropestairs.png", SCRIPT=lad, X2=192, Y2=288); t.npcs[2] = dict(IMAGE="ropestairs.png", SCRIPT=lad, X2=192, Y2=352)
    i1 = t.npcrt.instance(1, t.npcs[1]); i2 = t.npcrt.instance(2, t.npcs[2])
    import gs2npc
    h1, h2 = gs2npc.NpcHost(i1, t, t.npcrt), gs2npc.NpcHost(i2, t, t.npcrt)
    t.attached = 2
    check(h2.get_prop("playerattached") == 1.0 and h1.get_prop("playerattached") == 0.0, "playerattached: true for the NPC the player is attached to only")
    i1.touching = True; i2.touching = True
    i2.handle("detachplayer", [], None, None, None)
    check(t.attached is None and i1.touching is False and i2.touching is True, "detachplayer: the next ladder part gets playertouchsme again, not the one let go")
    # At the top the player is let go while still overlapping the ladder's blocking shape: walking out of it is allowed, walking deeper is not.
    t.pos = (184, 248)   # box (200..216, 280..296) overlaps NPC 1 (192..224, 288..352) by 16 x 8
    check(not t._out_of_wall(184, 244), "inside an NPC shape that did not let the player go: no exception")
    t._let_go = (1, t.clock())   # ladder part 1 let the player go at its top
    check(t.coll.blocked(t, 184, 244), "the step up still touches the ladder shape")
    check(t._out_of_wall(184, 244), "but it gets the player further out of it: allowed")
    check(not t._out_of_wall(184, 256), "a step deeper into it is not")
    t.pos = (100, 100); check(not t._out_of_wall(100, 92), "a player inside nothing gets no exception")
    print("ladder tests passed")

main()
