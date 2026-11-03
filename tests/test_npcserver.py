"""python3 test_npcserver.py : the local NPC server (server parts of GS2 weapons), loopback triggers, introspection API, sandboxed files."""
import os, re, shutil, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import offline, gs2src
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import gs2weapons_survey as W

def check(c, m):
    if not c: raise AssertionError(m)

def pump(s, n=25):
    for _ in range(n): s.runner.tick(); s.npcserver.tick(); s.gui.tick(); time.sleep(0.01)

def main():
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500))
    s.runner.add("-+Console", "", W.script_of(open(W.BASE + "/weapon%045%043Console.txt", encoding="latin1").read()))
    check("-+Console" in s.npcserver.scripts, f"server part attached {s.log}")
    g = s.gui; disp = g.objs["console_display"]; pump(s, 5)
    def cmd(t):
        before = len(disp.a["text"]); g.objs["console_chat"].a["text"] = t; g.focus = g.objs["console_chat"]; g.key(13, True); pump(s)
        return re.sub(r"<[^>]*>", "", disp.a["text"][before:]).strip()
    out = cmd("show 0 client")
    check(out.startswith("client (TGraalVar):") and "consoleposition: [2] {1,1}" in out and "consoleversion: 2" in out, f"client introspection: {out!r}")
    s.npcserver.vars["motd"] = "hello"
    check(cmd("server var server.motd") == 'server.motd (Server String): "hello"', "server var (string)")
    check(cmd("server var player.account") == 'player.account (Server String): "offline"', "server var player.account")
    out = cmd("server show 0 this"); check(out.startswith("this (Script):") and "console: -+Console (Script)" in out, f"server show: {out!r}")
    out = cmd("server show 4 this"); check("cmd_show: cmd_show (Function)" in out and "comserver" in out, f"server getfunctions + objecttype: {out!r}")
    check(cmd("nosuchcommand") == "Command doesn't exist", "unknown client command")
    it = s.npcserver.scripts["-+Console"].gs2
    def run(fn, *a): it.frames, it.withs = [], []; return it.call_sync(it.funcs[fn][0], list(a))
    check(run("comweapons", "offline") == ["-+Console"], "player.weapons")
    run("comadd", "offline", "-#GuiInputDialog"); check("-+GuiInputDialog" in run("comweapons", "offline"), "addweapon from the weapon library")
    run("comremove", "offline", "-#GuiInputDialog"); check(run("comweapons", "offline") == ["-+Console"], "removeweapon")
    check(s.npcserver.findplayer("nobody") is None, "findplayer of an unknown account")
    s.runner.add("-+Caller", "", "//#CLIENTSIDE\nfunction onPlayerChats() { client.res = Console.serverFunction(null, \"comweapons\", \"offline\"); client.done = 1; }\n")
    s.runner.broadcast("playerchats", chat="go"); t0 = time.time()
    while time.time() - t0 < 2 and not s.gs2_client.get("done"): pump(s, 1)
    check(s.gs2_client.get("res") == ["-+Console", "-+Caller"] and time.time() - t0 < 1.0, f"serverFunction round trip {s.gs2_client.get('res')}")
    host = type("H", (), {"global_obj": lambda self, l: None, "has_prop": lambda self, l: False, "call": lambda *a: None, "unknown": lambda *a: None})()
    it2 = gs2src.Interp(host, "function onCreated() { temp.a = {1, 2}; this.t = {5.type(), \"x\".type(), temp.a.type(), this.type(), nothing.type()}; temp.out = 0; out.add(1); out.add(2); this.n = out.size(); this.p = 12.5.pos(\".\"); this.s = \"abcdef\".substring(2, -1); }")
    list(it2.call_function("onCreated")); d = it2.this.d
    check(d["t"] == [0.0, 1.0, 3.0, 2.0, 4.0] and d["n"] == 2.0 and d["p"] == 2.0 and d["s"] == "cdef", f"type()/auto-array/pos/substring: {d}")
    check(gs2src.sandbox_path("../etc/passwd") is None and gs2src.sandbox_path("/etc/passwd").startswith(gs2src.SANDBOX) and gs2src.sandbox_path("a/../../b") is None, "sandbox paths")
    it3 = gs2src.Interp(host, "function onCreated() { temp.l = {\"one\", \"two\"}; l.savelines(\"test_tmp/lines.txt\"); temp.m = 0; m.add(\"x\"); m.loadlines(\"test_tmp/lines.txt\"); this.m = m; temp.f = 0; f.add(\"z\"); f.loadfolder(\"test_tmp/*.txt\"); this.f = f; }")
    try:
        list(it3.call_function("onCreated")); check(it3.this.d["m"] == ["one", "two"] and it3.this.d["f"] == ["lines.txt"], f"loadlines / savelines / loadfolder in the sandbox {it3.this.d}")
    finally: shutil.rmtree(os.path.join(gs2src.SANDBOX, "test_tmp"), ignore_errors=True)
    A = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500), account="TestA"); B = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (600, 500), account="TestB")
    srv = A.npcserver; srv.register(B)
    for sess_ in (A, B):
        for wn in ("-+Console", "-+System"): srv.addweapon(wn, sess_)
    def pump2(n=40):
        for _ in range(n):
            for sess_ in (A, B): sess_.runner.tick()
            srv.tick(); time.sleep(0.01)
    pump2(10)
    check([p.get("account") for p in srv.all_players()] == ["TestA", "TestB"], "allplayers lists both clients")
    other = srv.findplayer("testb"); check(other is not None and other.sess is B and other.get("x") == 37.5 and other.get("gmapx") == 7.0, f"findplayer by account (case-insensitive) -> the other client's level-local position and cell")
    check(srv.findplayer("nobody") is None, "unknown player")
    srv.scripts["-+System"].run("playall", ["pound.wav"], sender=A); pump2()
    played = lambda x: [p[0] for p in (x.audio.played if getattr(x, "audio", None) else [])]
    check("pound.wav" in played(A) and "pound.wav" in played(B), f"System.playall (with(i) + triggerclient) reached both clients: {played(A)} {played(B)}")
    A.audio.played.clear(); B.audio.played.clear()
    B.level_name = "elsewhere.nw"; srv.scripts["-+System"].run("playlevel", ["chest.wav"], sender=A); pump2()
    check("chest.wav" in played(A) and "chest.wav" not in played(B), f"System.playlevel only reaches players in the caller's level: {played(A)} {played(B)}")
    nid, n0 = next(iter(A.npcs.items())); n0["NAME"] = "TestNpc"; n0["ID"] = 4242
    f = srv.findnpc("testnpc"); check(f is not None and f.get("id") == 4242.0 and f.get("x") == n0["X2"] / 16, "findnpc by name")
    f.set("x", 7.5); check(n0["X2"] == 120 and srv.findnpc(4242, by_id=True).get("name") == "TestNpc", "findnpcbyid + setting x writes through")
    from npcserver import LevelSrv
    lv = LevelSrv(srv, A.level_name); check(len(lv.get("npcs")) == len([1 for n in A.npcs.values() if n.get("LEVEL") == A.level_name]) and lv.get("name") == A.level_name, "findlevel(...).npcs")
    check([p.get("account") for p in LevelSrv(srv, "elsewhere.nw").get("players")] == ["TestB"], "findlevel(...).players")
    sentB = []; B.send = lambda l: sentB.append(l); B.level_name = "turtlejunction-h4.nw"
    mover = """function onActionServerSide() {
  if (params[0] == "pos") { with (findplayer(params[1])) { x = params[2]; y = params[3]; } }
  if (params[0] == "cell") { with (findplayer(params[1])) { gmapx = params[2]; gmapy = params[3]; x = params[4]; y = params[5]; } }
  if (params[0] == "set2") { findplayer(params[1]).setlevel2("laboo-peak.nw", 30.5, 61); }
  if (params[0] == "talk") { findplayer(params[1]).chat = "moved by the server"; findplayer(params[1]).ani = "sit"; }
  if (params[0] == "nobody") { with (findplayer(params[1])) { x = 5; } }
  trigger("Done", null);
}
//#CLIENTSIDE
"""
    A.runner.add("-+Mover", "", mover)
    def move(*p):
        srv.trigger_server("-+Mover", list(p), "", A); pump2(15)
    move("pos", "TestB", 10, 12.5)
    check(B.pos == (160, 200), f"x / y assignments are level-local tiles and raw (no collision, like the real NPC server): {B.pos}")
    check(len(sentB) == 2 and sentB[0][0] == 0x20 + 2 and sentB[1][0] == 0x20 + 2, f"each assignment sent a player-props packet (X2, Y2): {sentB}")
    move("cell", "TestB", 8, 3, 20, 21)
    check(B.cell == (8, 3) and B.level_name == "turtlejunction-i4.nw" and B.pos == (320, 336) and B.me["GMAPLEVELX"] == 8, f"gmap cell move: cell={B.cell} level={B.level_name} pos={B.pos}")
    sentB.clear(); move("set2", "TestB")
    check(B.level_name == "laboo-peak.nw" and B.pos == (488, 976), f"setlevel2 warps the other client (offline: loads the level): {B.level_name} {B.pos}")
    move("talk", "TestB")
    check(B.me.get("MESSAGE") == "moved by the server" and B.me.get("GANI", "").startswith("sit"), f"chat + ani set by the server: {B.me.get('MESSAGE')} {B.me.get('GANI')}")
    other_pos = A.pos; move("nobody", "NoSuchPlayer"); check(A.pos == other_pos, "unknown player: nothing moves")
    from npcserver import RemoteSrv
    ghost = RemoteSrv(srv, 99, {"ACCOUNTNAME": "Ghost", "X2": 160, "Y2": 320, "GMAPLEVELX": 2, "GMAPLEVELY": 1}); ghost.set("x", 3)
    check(ghost.get("x") == 10.0 and ghost.get("gmapx") == 2.0 and "cannot move/modify Ghost" in A.log[-1], f"a player without a client here cannot be moved: {A.log[-1:]}")
    print("npcserver tests passed")

if __name__ == "__main__": main()
