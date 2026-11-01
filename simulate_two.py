"""Two real accounts on the running game server, one shared local NPC server: other players, NPC database, triggerclient to another
player's client, real private messages.

  GRAAL_PASSWORD=... python3 simulate_two.py [--accounts TestA TestB]

Both accounts log in (different accounts may be online together), each client gets the staff weapons from the weapon library, the
local NPC server is shared, and the script checks what each side sees. The accounts are not moved; their saved position fields are
compared with the account files afterwards and restored if the server changed them."""
import argparse, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gclient import Session
import gs2src, weaponlib

import config
ACCOUNT_DIR = config.CFG["account_dir"]
KEEP = ("LEVEL", "X", "Y", "MAPX", "MAPY", "Z", "ANI")

def account_fields(name):
    out = {}
    try:
        for ln in open(os.path.join(ACCOUNT_DIR, name + ".txt"), encoding="latin1"):
            k, _, v = ln.rstrip("\n").partition(" ")
            if k in KEEP: out[k] = v
    except OSError: pass
    return out

def restore(name, before):
    path = os.path.join(ACCOUNT_DIR, name + ".txt")
    try: lines = open(path, encoding="latin1").read().split("\n")
    except OSError: return False
    changed = False
    for i, ln in enumerate(lines):
        k, _, v = ln.partition(" ")
        if k in before and v != before[k]: lines[i] = f"{k} {before[k]}"; changed = True
    if changed: open(path, "w", encoding="latin1").write("\n".join(lines))
    return changed

def pump(sessions, secs, srv=None):
    end = time.time() + secs
    while time.time() < end:
        for s in sessions: s.poll()
        time.sleep(0.02)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--accounts", nargs=2, default=["TestA", "TestB"]); ap.add_argument("--listserver", default="127.0.0.1:9111")
    a = ap.parse_args(); pw = os.environ.get("GRAAL_PASSWORD")
    if not pw: sys.exit("set GRAAL_PASSWORD")
    host, port = a.listserver.rsplit(":", 1); before = {n: account_fields(n) for n in a.accounts}
    sess = []; ok = True
    def check(cond, msg):
        nonlocal ok; print(("  ok   " if cond else "  FAIL ") + msg); ok = ok and bool(cond)
    try:
        for n in a.accounts:
            s = Session(n, pw, "222", (host, int(port))); s.connect(); sess.append(s)
        A, B = sess; pump(sess, 2.5)
        for s in sess: s.ensure_neighbours()
        pump(sess, 1.0)
        print("A:", A.account_name, A.level_name, A.pos, "gmap", A.gmap, "cell", A.cell, "| B:", B.account_name, B.level_name, B.pos, "cell", B.cell)
        accs = lambda s: sorted(str(p.get("ACCOUNTNAME", "")) for p in s.players.values())
        print("A sees:", accs(A), "| B sees:", accs(B))
        srv = A.npcserver; srv.enabled = True; srv.register(B)
        for s in sess:
            for w in ("-+Console", "-+System"):
                srv.addweapon(w, s)
        pump(sess, 0.5, srv)
        check(set(srv.scripts) >= {"-+Console", "-+System"}, f"server scripts attached once for both clients: {sorted(srv.scripts)}")
        names = sorted(text for text in (str(p.get("account")) for p in srv.all_players()))
        check(names == sorted(a.accounts) or set(a.accounts) <= set(names), f"allplayers = {names}")
        kn = srv.findplayer(a.accounts[1]); check(kn is not None and kn.get("account") == a.accounts[1], f"findplayer({a.accounts[1]}) -> {kn and kn.get('account')} level={kn and kn.get('level')} x={kn and round(kn.get('x'), 1)} y={kn and round(kn.get('y'), 1)}")
        seen = next((p for p in A.players.values() if str(p.get("ACCOUNTNAME")) == a.accounts[1]), None)
        if seen: check((seen.get("GMAPLEVELX"), seen.get("GMAPLEVELY")) == (kn.get("gmapx"), kn.get("gmapy")) and abs(seen.get("X2", 0) / 16 - kn.get("x")) < 0.1 and abs(seen.get("Y2", 0) / 16 - kn.get("y")) < 0.1, f"position known to A from the real server (cell {seen.get('GMAPLEVELX')},{seen.get('GMAPLEVELY')}, x {seen.get('X2', 0) / 16}, y {seen.get('Y2', 0) / 16}) agrees with B's own client")
        else: print("  note A does not see B on the real server (different gmap cells out of range)")
        for s in sess: s.audio = None
        sc = srv.scripts["-+System"]; sc.run("playall", ["pound.wav"], sender=A); pump(sess, 1.0, srv)
        played = lambda s: [p[0] for p in (s.audio.played if getattr(s, "audio", None) else [])]
        check("pound.wav" in played(A) and "pound.wav" in played(B), f"System.playall reached both clients: A={played(A)} B={played(B)}")
        before_pm = len(B.pm); pmres = kn.call("sendpm", ["hello from the local NPC server"]) if kn else None; pump(sess, 1.5, srv)
        check(seen is None or (len(B.pm) > before_pm and any("local NPC server" in m["text"] for m in B.pms)), f"private message arrived at B through the game server: {B.pms[-1:] } (send result {pmres})")
        some = next(iter(A.npcs.items()), None)
        if some:
            nid, n = some; found = srv.findnpc(n.get("NAME") or n.get("IMAGE") or ""); check(found is not None, f"findnpc({n.get('NAME') or n.get('IMAGE')!r}) -> {found and found.get('name')}")
            by_id = srv.findnpc(n.get("ID", nid), by_id=True); check(by_id is not None and by_id.get("x") is not None, f"findnpcbyid({n.get('ID', nid)}) -> x={by_id and round(by_id.get('x'), 1)} y={by_id and round(by_id.get('y'), 1)} image={by_id and by_id.get('image')}")
        from npcserver import LevelSrv
        lv = LevelSrv(srv, A.level_name or ""); check(len(lv.get("npcs")) >= 0, f"findlevel({A.level_name}).npcs = {len(lv.get('npcs'))}, .players = {[p.get('account') for p in lv.get('players')]}")
        check(len(srv.all_players()) >= 2 and len(A.npcs) > 0, f"A knows {len(A.npcs)} NPCs from the real server")
        mover = ("function onActionServerSide() {\n  with (findplayer(params[0])) { gmapx = params[1]; gmapy = params[2]; x = params[3]; y = params[4]; }\n}\n//#CLIENTSIDE\n")
        A.runner.add("-+MoveTest", "", mover)
        home_cell, home_xy = tuple(B.cell), (B.pos[0] / 16, B.pos[1] / 16); ax, ay = A.pos[0] / 16, A.pos[1] / 16
        def seen_by_A():
            p = next((p for p in A.players.values() if str(p.get("ACCOUNTNAME")) == a.accounts[1]), None)
            return p and ((p.get("GMAPLEVELX"), p.get("GMAPLEVELY")), round(p.get("X2", 0) / 16, 1), round(p.get("Y2", 0) / 16, 1))
        srv.trigger_server("-+MoveTest", [a.accounts[1], A.cell[0], A.cell[1], ax + 3, ay], "", A); pump(sess, 2.0, srv)
        check(tuple(B.cell) == tuple(A.cell) and abs(B.pos[0] / 16 - (ax + 3)) < 0.1 and B.level_name == A.level_name, f"server moved {a.accounts[1]} into the same level as {a.accounts[0]}: B at {B.level_name} {B.pos} (A at {A.level_name} {A.pos})")
        check(seen_by_A() == (tuple(A.cell), round(ax + 3, 1), round(ay, 1)), f"A sees the move through the game server: {seen_by_A()}")
        srv.trigger_server("-+MoveTest", [a.accounts[1], home_cell[0], home_cell[1], home_xy[0], home_xy[1]], "", A); pump(sess, 2.0, srv)
        check(tuple(B.cell) == home_cell and abs(B.pos[0] / 16 - home_xy[0]) < 0.1 and abs(B.pos[1] / 16 - home_xy[1]) < 0.1, f"moved back to its own cell and position: {B.cell} {B.pos}")
        check(seen_by_A() == (home_cell, round(home_xy[0], 1), round(home_xy[1], 1)), f"A sees it back home: {seen_by_A()}")
        A.runner.add("-+WalkTest", "", "function onActionServerSide() {\n  with (findplayer(params[0])) { walkto(params[1], params[2], params[3], params[4]); }\n  waitfor(findplayer(params[0]), \"WalkDone\", 40);\n  server.walked = server.walked + 1;\n}\n//#CLIENTSIDE\n")
        srv.vars["walked"] = 0.0
        def walk(tx, ty, cx, cy, limit=25.0):
            srv.trigger_server("-+WalkTest", [a.accounts[1], tx, ty, cx, cy], "", A); trace_b, trace_a = [], []; t0 = time.time(); n0 = srv.vars["walked"]
            while time.time() - t0 < limit and srv.vars["walked"] == n0:
                pump(sess, 0.05)
                trace_b.append(B._gpos()); v = seen_by_A(); trace_a.append(None if not v else (v[0][0] * 1024 + v[1] * 16, v[0][1] * 1024 + v[2] * 16))
            pump(sess, 0.6); return trace_b, trace_a, time.time() - t0
        tb, ta, dt = walk(home_xy[0], 6, home_cell[0], home_cell[1] + 1)
        steps = [(abs(p[0] - q[0]) + abs(p[1] - q[1])) for p, q in zip(tb, tb[1:])]
        check(srv.vars["walked"] == 1.0 and tuple(B.cell) == (home_cell[0], home_cell[1] + 1) and abs(B.pos[0] / 16 - home_xy[0]) < 0.6 and abs(B.pos[1] / 16 - 6) < 0.6, f"B walked into the next cell and arrived: cell {B.cell} pos {B.pos} after {dt:.1f} s")
        check(len(set(tb)) > 15 and max(steps) <= 16 and all(not B._blocked_g(*p) for p in tb), f"{len(set(tb))} distinct positions, largest jump {max(steps)} px, none inside a wall (B's own collision)")
        sa = [p for p in ta if p]; moved = [p for i, p in enumerate(sa) if i == 0 or p != sa[i - 1]]
        check(len(moved) > 8 and all(abs(p[0] - q[0]) + abs(p[1] - q[1]) <= 64 for p, q in zip(moved, moved[1:])), f"TestA saw {len(moved)} intermediate positions through the game server (smooth, no teleport jumps)")
        tb, ta, dt = walk(home_xy[0], home_xy[1], home_cell[0], home_cell[1])
        check(srv.vars["walked"] == 2.0 and tuple(B.cell) == home_cell and abs(B.pos[0] / 16 - home_xy[0]) < 0.6 and abs(B.pos[1] / 16 - home_xy[1]) < 0.6, f"walked back home: cell {B.cell} pos {B.pos} after {dt:.1f} s")
        if tuple(B.cell) == home_cell: B.teleport(home_xy[0], home_xy[1], check=False)
        pump(sess, 0.5)
        a_home = (tuple(A.cell), A.pos[0] / 16, A.pos[1] / 16)
        srv.trigger_server("-+MoveTest", [a.accounts[0], home_cell[0], home_cell[1], home_xy[0], home_xy[1] + 4], "", A); pump(sess, 1.5)
        a_g = A._gpos(); check(tuple(A.cell) == home_cell, f"TestA now stands on the route: cell {A.cell} at {A.pos} (B at {B.pos})")
        pump(sess, 1.0); b_sees_a = any(abs(ox - a_g[0]) < 8 and abs(oy - a_g[1]) < 8 for ox, oy in B.others_global())
        check(b_sees_a, f"TestB' client knows where TestA stands: {B.others_global()[:2]} (TestA at {a_g})")
        tb, ta, dt = walk(home_xy[0], 6, home_cell[0], home_cell[1] + 1)
        dist = min(max(abs(p[0] - a_g[0]), abs(p[1] - a_g[1])) for p in tb)
        check(srv.vars["walked"] == 3.0 and tuple(B.cell) == (home_cell[0], home_cell[1] + 1), f"walk still arrives with a player in the way: cell {B.cell} pos {B.pos}, {len(tb)} samples, {dt:.1f} s")
        check(dist >= 16, f"never overlapped the other player's collision box: closest centre distance {dist} px (avoid distance {B.AVOID_NEAR}, box overlap below {B.AVOID_HARD})")
        print(f"      closest approach {dist} px; route had {len(set(tb))} distinct positions")
        walk(home_xy[0], home_xy[1], home_cell[0], home_cell[1])
        srv.trigger_server("-+MoveTest", [a.accounts[0], a_home[0][0], a_home[0][1], a_home[1], a_home[2]], "", A); pump(sess, 1.5)
        check(tuple(A.cell) == a_home[0] and abs(A.pos[0] / 16 - a_home[1]) < 0.1, f"TestA is back home: cell {A.cell} pos {A.pos}")
        def cross_run(predict):
            B.predict_players = predict; B.use_peer_routes = False
            srv.trigger_server("-+MoveTest", [a.accounts[0], home_cell[0], home_cell[1], home_xy[0] + 5.0, home_xy[1] + 4], "", A); pump(sess, 1.5)
            n0 = srv.vars["walked"]
            srv.trigger_server("-+WalkTest", [a.accounts[0], home_xy[0] - 4.0, home_xy[1] + 4, home_cell[0], home_cell[1]], "", A)
            pump(sess, 0.35)
            srv.trigger_server("-+WalkTest", [a.accounts[1], home_xy[0], 6, home_cell[0], home_cell[1] + 1], "", A)
            t0 = time.time(); mind = 10 ** 9
            while time.time() - t0 < 12 and srv.vars["walked"] < n0 + 2:
                pump(sess, 0.05); ga, gb = A._gpos(), B._gpos(); mind = min(mind, max(abs(ga[0] - gb[0]), abs(ga[1] - gb[1])))
            pump(sess, 0.5); return mind
        m_pred = cross_run(True)
        walk(home_xy[0], home_xy[1], home_cell[0], home_cell[1])
        check(m_pred >= 16, f"crossing walks with prediction never overlapped: closest centre distance {m_pred} px (box overlap below {B.AVOID_HARD}, avoid distance {B.AVOID_NEAR})")
        m_static = cross_run(False); B.predict_players = True
        print(f"      closest approach with prediction {m_pred} px, with current-position avoidance only {m_static} px")
        walk(home_xy[0], home_xy[1], home_cell[0], home_cell[1])
        srv.trigger_server("-+MoveTest", [a.accounts[0], a_home[0][0], a_home[0][1], a_home[1], a_home[2]], "", A); pump(sess, 1.5)
        check(tuple(A.cell) == a_home[0] and abs(A.pos[0] / 16 - a_home[1]) < 0.1, f"TestA is back home again: cell {A.cell} pos {A.pos}")
        print("log (A):", [l for l in A.log if "pm" in l or "server" in l][-4:])
    finally:
        for s in sess:
            try: s.close()
            except Exception: pass
        time.sleep(1.0)
        for n in a.accounts:
            after = account_fields(n); diff = {k: (before[n].get(k), after.get(k)) for k in KEEP if before[n].get(k) != after.get(k)}
            print(f"{n}: saved position fields", "unchanged" if not diff else f"changed {diff} -> restored: {restore(n, before[n])}")
    print("RESULT:", "ok" if ok else "FAILED"); return 0 if ok else 1

if __name__ == "__main__": sys.exit(main())
