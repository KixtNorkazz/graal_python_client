"""python3 test_walk.py : path finding, smooth server-commanded walking with collision, checked teleports."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline, pathing

def check(c, m):
    if not c: raise AssertionError(m)

def run_walk(s, limit=2000):
    """Drive the walk to its end with a fake clock (the real step is 50 ms); returns the visited global positions."""
    seen = [s._gpos()]
    for _ in range(limit):
        if not s.walking_to(): break
        s._walk_tick(s.walk_task["next"])
        if s._gpos() != seen[-1]: seen.append(s._gpos())
    return seen

def main():
    wall = lambda x, y: x == 80 and y != 160
    p = pathing.find_path(wall, (0, 0), (160, 0))
    check(p and p[-1] == (160, 0) and all(not wall(*q) for q in p), f"path around a wall: {len(p or [])} steps")
    check(len(p) == (160 + 2 * 160) // 8, f"shortest: detour through the gap = 160/8 + 2*160/8 = {(160 + 320) // 8} steps, got {len(p)}")
    check(all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 8 for a, b in zip([(0, 0)] + p, p)), "axis moves of one lattice step")
    check(pathing.find_path(lambda x, y: x == 80, (0, 0), (160, 0)) is None, "enclosed: no path")
    check(pathing.find_path(lambda x, y: (x, y) == (24, 0), (0, 0), (24, 0)) is None, "blocked goal: no path")
    check(pathing.find_path(wall, (8, 8), (8, 8)) == [], "already there")
    check(pathing.nearest_free(lambda x, y: x < 40 and y < 40, (8, 8)) in ((40, 8), (8, 40)), "nearest free spot")
    check([pathing.direction((0, 0), q) for q in ((8, 0), (-8, 0), (0, 8), (0, -8))] == list("RLDU"), "directions")

    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); sent = []; s.send = lambda l: sent.append(l); done = []; s.on_walk_done = done.append
    start = s._gpos(); goal_tiles = (31, 24)
    check(not s._blocked_g(*start), "start position is free")
    check(s.walk_to(*goal_tiles), "a path exists on the bridge")
    seen = run_walk(s)
    check(done == ["arrived"] and not s.walking_to(), f"walk finished: {done}")
    check(s.pos == (31 * 16, 24 * 16) and s.cell == (7, 3), f"arrived at the goal tile: {s.pos} {s.cell}")
    check(all(not s._blocked_g(*g) for g in seen), "no step on a wall or an NPC shape")
    check(all(abs(a[0] - b[0]) + abs(a[1] - b[1]) == 8 for a, b in zip(seen, seen[1:])), "exactly one 8 px step per 50 ms tick")
    check(len(sent) >= len(seen) - 1 and s.me["GANI"] == s.resolve_ani("idle"), f"every step sent player props; idle gani at the end ({len(sent)} packets, {s.me['GANI']})")
    s2 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); s2.send = lambda l: None
    check(s2.walk_to(8, 31), "left bank reachable"); seen2 = run_walk(s2)
    manhattan = abs(8 * 16 - 496) // 8 + abs(31 * 16 - 496) // 8
    check(abs(s2.pos[0] - 128) <= 48 and abs(s2.pos[1] - 496) <= 48 and len(seen2) - 1 > manhattan + 20 and all(not s2._blocked_g(*g) for g in seen2), f"detour around obstacles: {len(seen2) - 1} steps (straight line would be {manhattan})")
    s3 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (992, 496)); s3.send = lambda l: None
    check(s3.walk_to(3, 31, (8, 3)), "path into the next cell"); run_walk(s3)
    check(s3.cell == (8, 3) and s3.level_name == "turtlejunction-i4.nw" and s3.pos == (48, 496) and s3.me["GMAPLEVELX"] == 8, f"walked over the cell border: cell {s3.cell} {s3.level_name} {s3.pos}")
    s4 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); s4.send = lambda l: None; r4 = []; s4.on_walk_done = r4.append
    cx4, cy4 = s4.cell
    wall_t = next((tx, ty) for ty in range(0, 64, 2) for tx in range(0, 64, 2) if s4._blocked_g(cx4 * 1024 + tx * 16, cy4 * 1024 + ty * 16) and pathing.nearest_free(s4._blocked_g, (cx4 * 1024 + tx * 16, cy4 * 1024 + ty * 16)) is None)
    check(s4.walk_to(*wall_t) is False and r4 == ["blocked"] and not s4.walking_to(), f"a goal deep inside rock is refused: {wall_t} {r4}")
    s.walk_to(31, 20); s.teleport(5, 5, check=False); check(not s.walking_to(), "teleport cancels the walk")

    s6 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 498)); s6.send = lambda l: None; s6.walk_to(31, 24); run_walk(s6)
    check(abs(s6.pos[0] - 31 * 16) <= 4 and abs(s6.pos[1] - 24 * 16) <= 4, f"odd start position still arrives: {s6.pos}")

    s5 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); s5.send = lambda l: None
    blocked_px = (wall_t[0] * 16, wall_t[1] * 16)
    check(s5.teleport(wall_t[0], wall_t[1]) is False, "teleport into rock is refused (no free spot within 3 tiles)")
    cx5, cy5 = s5.cell; G = lambda tx, ty: (cx5 * 1024 + tx * 16, cy5 * 1024 + ty * 16)
    edge = next((tx, ty) for ty in range(1, 63) for tx in range(1, 63) if s5._blocked_g(*G(tx, ty)) and not s5._blocked_g(*G(tx + 1, ty)))
    check(s5.teleport(*edge) and not s5._blocked_g(*s5._gpos()) and abs(s5.pos[0] - edge[0] * 16) <= 48, f"teleport onto a wall edge moves to the nearest free spot: {edge} -> {s5.pos}")
    check(s5.teleport(*wall_t, check=False) and s5.pos == blocked_px, "check=False places exactly (like a raw NPC-server assignment)")

    A = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496), account="TestA"); B = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (400, 496), account="TestB")
    A.send = lambda l: None; B.send = lambda l: None; srv = A.npcserver; srv.register(B)
    A.runner.add("-+Walker", "", """function onActionServerSide() {
  temp.ok = findplayer(params[0]).walkto(params[1], params[2]);
  server.walkstart = temp.ok;
  waitfor(findplayer(params[0]), "WalkDone", 30);
  server.walkend = findplayer(params[0]).x @ "," @ findplayer(params[0]).y @ "," @ findplayer(params[0]).walking;
}
//#CLIENTSIDE
""")
    srv.trigger_server("-+Walker", ["TestB", 31, 24], "", A)
    t0 = time.time()
    while time.time() - t0 < 0.4: A.runner.tick(); srv.tick(); time.sleep(0.01)
    check(srv.vars.get("walkstart") == 1.0 and B.walking_to(), f"server script started the walk: {srv.vars}")
    now = time.time() + 1
    for _ in range(400):
        if not B.walking_to(): break
        now += 0.05; B._walk_tick(now)
    t0 = time.time()
    while time.time() - t0 < 0.5 and "walkend" not in srv.vars: A.runner.tick(); srv.tick(); time.sleep(0.01)
    check(srv.vars.get("walkend") == "31,24,0", f"waitfor(player, 'WalkDone') resumed the server script after arrival: {srv.vars}")
    pathing_cost = lambda ox, oy: (lambda x, y: 64 if abs(x - ox) < 24 and abs(y - oy) < 24 else 0)
    p_plain = pathing.find_path(lambda x, y: False, (0, 0), (160, 0)); p_avoid = pathing.find_path(lambda x, y: False, (0, 0), (160, 0), cost=pathing_cost(80, 0))
    check(len(p_plain) == 20 and len(p_avoid) > 20 and all(abs(q[0] - 80) >= 24 or abs(q[1]) >= 24 for q in p_avoid), f"A* detours around a soft obstacle: {len(p_plain)} -> {len(p_avoid)} steps")
    corridor = lambda x, y: y != 0
    p_cor = pathing.find_path(corridor, (0, 0), (160, 0), cost=pathing_cost(80, 0)); check(p_cor is not None and len(p_cor) == 20, "in a corridor the soft obstacle is crossed instead of failing")

    def pair(pos_walker, pos_other, cell=(7, 3)):
        W = offline.OfflineSession("turtlejunction-.gmap", cell, pos_walker, account="TestA"); O = offline.OfflineSession("turtlejunction-.gmap", cell, pos_other, account="TestB")
        W.send = lambda l: None; O.send = lambda l: None; W.npcserver.register(O); return W, O
    probe = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); cxp, cyp = probe.cell; Gp = lambda tx, ty: (cxp * 1024 + tx * 16, cyp * 1024 + ty * 16)
    area = next((tx, ty) for ty in range(8, 56) for tx in range(2, 44) if all(not probe._blocked_g(*Gp(tx + dx, ty + dy)) for dx in range(0, 18) for dy in range(-4, 5)))
    ax_, ay_ = area; W, O = pair((ax_ * 16, ay_ * 16), ((ax_ + 8) * 16, ay_ * 16)); W.walk_to(ax_ + 16, ay_)
    seen_w = run_walk(W); og = O._gpos(); mind = min(max(abs(p[0] - og[0]), abs(p[1] - og[1])) for p in seen_w)
    check(W.pos == ((ax_ + 16) * 16, ay_ * 16) and mind >= 24 and len(seen_w) - 1 > 32, f"walk detours around a standing player: min distance {mind} px, {len(seen_w) - 1} steps (straight: 32)")
    W2, O2 = pair((ax_ * 16, ay_ * 16), ((ax_ + 8) * 16, ay_ * 16)); W2.avoid_players = False; W2.walk_to(ax_ + 16, ay_); sw2 = run_walk(W2); og2 = O2._gpos()
    check(len(sw2) - 1 == 32 and min(max(abs(p[0] - og2[0]), abs(p[1] - og2[1])) for p in sw2) < 16, "with avoidplayers off the walk goes straight through")
    W3, O3 = pair((ax_ * 16, ay_ * 16), ((ax_ + 12) * 16, ay_ * 16)); W3.walk_to(ax_ + 12, ay_); run_walk(W3); og3 = O3._gpos(); g3 = W3._gpos()
    check(max(abs(g3[0] - og3[0]), abs(g3[1] - og3[1])) >= 16, f"does not end on top of the other player: {g3} vs {og3}")
    W4, O4 = pair((ax_ * 16, ay_ * 16), (ax_ * 16, (ay_ + 4) * 16)); W4.walk_to(ax_ + 16, ay_); seen4 = []
    for k in range(300):
        if not W4.walking_to(): break
        if k == 6: O4.teleport(ax_ + 9, ay_, check=False)
        W4._walk_tick(W4.walk_task["next"]); seen4.append(W4._gpos())
    o4 = O4._gpos(); late = seen4[12:]
    check(W4.pos == ((ax_ + 16) * 16, ay_ * 16) and min(max(abs(p[0] - o4[0]), abs(p[1] - o4[1])) for p in late) >= 16, f"replanned around a player who stepped into the path: min distance after the step {min(max(abs(p[0] - o4[0]), abs(p[1] - o4[1])) for p in late)}")
    bx = 496; W5, O5 = pair((bx, 496), (bx, 464)); W5.send = lambda l: None; W5.walk_to(31, 24)
    ticks = []; moved_at = None
    for k in range(300):
        if not W5.walking_to(): break
        before_ = W5._gpos(); W5._walk_tick(W5.walk_task["next"]); ticks.append(W5._gpos() != before_)
    check(W5.pos == (31 * 16, 24 * 16), f"arrived although a player stood in the corridor: {W5.pos}")
    W6 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax_ * 16, ay_ * 16), account="TestA"); W6.send = lambda l: None; W6.walk_to(ax_ + 4, ay_)
    blocker = {"on": True, "at": (W6._gpos()[0] + 8, W6._gpos()[1])}; W6.others_global = lambda: [blocker["at"]] if blocker["on"] else []; W6._avoid_cost = lambda others: None
    stalled = 0; last = W6._gpos()
    for k in range(200):
        if not W6.walking_to(): break
        if k == 20: blocker["on"] = False
        W6._walk_tick(W6.walk_task["next"]); g6 = W6._gpos(); stalled += 1 if g6 == last and k <= 20 else 0; last = g6
    check(stalled >= 15 and W6.pos == ((ax_ + 4) * 16, ay_ * 16), f"waited while the next step was occupied ({stalled} ticks), then arrived: {W6.pos}")
    plan = {}
    def crossing(predict):
        Wk, Ok = pair((ax_ * 16, ay_ * 16), ((ax_ + 2) * 16, (ay_ - 4) * 16)); Ok.avoid_players = False; Wk.predict_players = predict
        fake = [time.time()]; Wk.clock = Ok.clock = lambda: fake[0]
        Ok.walk_to(ax_ + 2, ay_ + 4); now = fake[0]; mind = 10 ** 9; wpath = []; plan[predict] = None
        for k in range(120):
            now += 0.05; fake[0] = now
            if k == 4: Wk.walk_to(ax_ + 8, ay_); Wk.walk_task["next"] = now; plan[predict] = list(Wk.walk_task["path"])
            Ok._walk_task_next = None
            for X in (Wk, Ok): X._track_update(now)
            if Ok.walking_to(): Ok._walk_tick(now)
            if Wk.walking_to(): Wk._walk_tick(now)
            if k >= 4:
                a_, b_ = Wk._gpos(), Ok._gpos(); mind = min(mind, max(abs(a_[0] - b_[0]), abs(a_[1] - b_[1]))); wpath.append(a_)
            if k > 4 and not Wk.walking_to() and not Ok.walking_to(): break
        return mind, Wk.pos, len(wpath)
    mind_p, endp, lenp = crossing(True); mind_s, ends, lens = crossing(False)
    check(endp == ((ax_ + 8) * 16, ay_ * 16) and ends == endp, f"both arrive: {endp} {ends}")
    check(mind_p >= 24, f"with prediction the walker keeps its distance from a player crossing its route: closest {mind_p} px (without: {mind_s} px)")
    row_y = Gp(ax_, ay_)[1]; straight = all(q[1] == row_y for q in plan[False]); bent = any(q[1] != row_y for q in plan[True])
    check(straight and bent, f"the first plan differs: without prediction the straight line ({len(plan[False])} steps), with prediction a path that avoids the crossing point ({len(plan[True])} steps)")
    Wv, Ov = pair((ax_ * 16, ay_ * 16), ((ax_ + 8) * 16, ay_ * 16)); fv = [time.time()]; Wv.clock = Ov.clock = lambda: fv[0]; Ov.walk_to(ax_ + 8, ay_ + 4); nv = fv[0]
    for k in range(10): nv += 0.05; fv[0] = nv; Wv._track_update(nv); Ov._walk_tick(nv)
    pr = Wv.predicted_others(nv)[0]; og = Ov._gpos()
    check(abs(pr[0][0] - og[0]) <= 8 and pr[10][1] > og[1] and abs(pr[10][1] - og[1] - 80) <= 24, f"predicted 0.5 s ahead: moving down 80 px: now {og}, +10 steps {pr[10]}")
    for k in range(12): nv += 0.05
    st = Wv.predicted_others(nv + 1.0)[0]; check(all(p == st[0] for p in st), "a player that stopped (no update for 0.4 s) is predicted to stay")
    import collections
    def set_route(Sx, nodes, clk):
        Sx.walk_task = dict(path=collections.deque(nodes), goal=nodes[-1], next=clk(), first=True, replans=0, tick=0, wait=0, avoid_replans=0, quiet_until=0)
    def L_route(Sx, down, right):
        g = Sx._gpos(); nodes = [(g[0], g[1] + 8 * i) for i in range(1, down + 1)]
        return nodes + [(nodes[-1][0] + 8 * i, nodes[-1][1]) for i in range(1, right + 1)]
    def remote_pair(pos_walker, pos_other, route=None):
        """A walker and a 'remote' player: the walker only sees the other player's position (like props from the game server), not its route."""
        Wr = offline.OfflineSession("turtlejunction-.gmap", (7, 3), pos_walker, account="TestA"); Or = offline.OfflineSession("turtlejunction-.gmap", (7, 3), pos_other, account="Ghost")
        Wr.send = lambda l: None; Or.send = lambda l: None; Or.avoid_players = False; fk = [time.time()]; Wr.clock = Or.clock = lambda: fk[0]
        def publish():
            Wr.players[7] = dict(ACCOUNTNAME="Ghost", X2=Or.pos[0], Y2=Or.pos[1], GMAPLEVELX=Or.cell[0], GMAPLEVELY=Or.cell[1])
        publish(); return Wr, Or, fk, publish
    Wt, Ot, fk, publish = remote_pair((ax_ * 16, ay_ * 16), ((ax_ + 1) * 16, (ay_ - 4) * 16)); set_route(Ot, L_route(Ot, 6, 10), Ot.clock); now = fk[0]
    for k in range(10):
        now += 0.05; fk[0] = now; Ot._walk_tick(now); publish(); Wt._track_update(now)
    res = {}
    for aware in (True, False):
        Wt.turn_aware = aware; pr = Wt.predicted_others(now)[0]; res[aware] = (pr[8][0] - pr[0][0], pr[8][1] - pr[0][1])
    check(res[True][0] > 56 and abs(res[True][1]) < 16, f"turn-aware: 0.4 s ahead the other player moves right ({res[True][0]:.0f}, {res[True][1]:.0f}) px")
    check(res[False][0] < res[True][0] - 10 and res[False][1] > 16, f"without turn tracking the average still drags down ({res[False][0]:.0f}, {res[False][1]:.0f}) px")
    Wt.turn_aware = True
    Ww, Ow, fk2, pub2 = remote_pair((ax_ * 16, ay_ * 16), ((ax_ + 2) * 16, (ay_ - 4) * 16)); set_route(Ow, [(Ow._gpos()[0], Ow._gpos()[1] + 8 * i) for i in range(1, 80)], Ow.clock); n2 = fk2[0]
    wall_row = None
    for k in range(10): n2 += 0.05; fk2[0] = n2; Ow._walk_tick(n2); pub2(); Ww._track_update(n2)
    blocked_px = Ww._blocked_g
    Ww._blocked_g = lambda x, y: y >= Ow._gpos()[1] + 48 or blocked_px(x, y)
    paths = Ww.predicted_others(n2); Ww._blocked_g = blocked_px
    check(len(paths) == 3, f"main path + two wall-sliding alternatives: {len(paths)} hypotheses")
    end = [p[-1] for p in paths]; base = paths[0][0]
    check(abs(end[0][0] - base[0]) < 1 and abs(end[1][0] - base[0]) > 20 and abs(end[2][0] - base[0]) > 20 and (end[1][0] - base[0]) * (end[2][0] - base[0]) < 0, f"the alternatives slide left and right along the wall: {[(round(e[0] - base[0]), round(e[1] - base[1])) for e in end]}")
    Wp, Op = pair((ax_ * 16, ay_ * 16), ((ax_ + 1) * 16, (ay_ - 4) * 16)); fkp = [time.time()]; Wp.clock = Op.clock = lambda: fkp[0]; Op.avoid_players = False
    set_route(Op, L_route(Op, 6, 10), Op.clock); nowp = fkp[0]; Wp._track_update(nowp); pred = Wp.predicted_others(nowp)[0]; actual = [Op._gpos()]
    for k in range(40): nowp += 0.05; fkp[0] = nowp; Op._walk_tick(nowp); actual.append(Op._gpos())
    err = max(max(abs(a_[0] - b_[0]), abs(a_[1] - b_[1])) for a_, b_ in zip(pred[:30], actual[:30]))
    check(err <= 8, f"the predicted path of a walking local client matches where it really went (turn after 6 steps): max error {err} px over 30 steps")
    def turn_cross(aware):
        Wc, Oc, fkc, pubc = remote_pair((ax_ * 16 + 64, (ay_ - 4) * 16), (ax_ * 16, (ay_ - 4) * 16)); Wc.turn_aware = aware
        set_route(Oc, [(Oc._gpos()[0], Oc._gpos()[1] + 8 * i) for i in range(1, 7)] + [(Oc._gpos()[0] + 8 * i, Oc._gpos()[1] + 48) for i in range(1, 13)], Oc.clock)
        nowc = fkc[0]; mind = 10 ** 9; pubc()
        for k in range(60):
            nowc += 0.05; fkc[0] = nowc
            if Oc.walking_to(): Oc._walk_tick(nowc)
            pubc(); Wc._track_update(nowc)
            if k == 3: Wc.walk_to(ax_ + 4, ay_ + 4); Wc.walk_task["next"] = nowc
            if Wc.walking_to(): Wc._walk_tick(nowc)
            if k >= 3: a_, b_ = Wc._gpos(), Oc._gpos(); mind = min(mind, max(abs(a_[0] - b_[0]), abs(a_[1] - b_[1])))
        return mind, Wc.pos
    m_aware, e_aware = turn_cross(True); m_blind, e_blind = turn_cross(False)
    check(abs(e_aware[0] - (ax_ + 4) * 16) <= 24 and abs(e_aware[1] - (ay_ + 4) * 16) <= 24 and m_aware >= 24 and m_aware > m_blind, f"walk across the path of a player who turns into it: closest {m_aware} px with turn prediction, {m_blind} px without (arrived at {e_aware})")
    import random
    def jitter_run(mode, seed):
        rnd = random.Random(seed); Wj, Oj, fkj, _ = remote_pair((ax_ * 16 + 64, (ay_ - 4) * 16), (ax_ * 16, (ay_ - 4) * 16))
        if mode == "static": Wj.predict_players = False
        elif mode == "blind": Wj.turn_aware = False
        g0 = Oj._gpos(); set_route(Oj, [(g0[0], g0[1] + 8 * i) for i in range(1, 7)] + [(g0[0] + 8 * i, g0[1] + 48) for i in range(1, 13)], Oj.clock)
        nowj = fkj[0]; mind = 10 ** 9; pend = collections.deque()
        for k in range(70):
            nowj += 0.05; fkj[0] = nowj
            if Oj.walking_to(): Oj._walk_tick(nowj)
            pend.append((nowj + rnd.uniform(0, 0.15), (Oj.pos[0], Oj.pos[1])))
            while pend and pend[0][0] <= nowj:
                _, p_ = pend.popleft(); Wj.players[7] = dict(ACCOUNTNAME="Ghost", X2=p_[0], Y2=p_[1], GMAPLEVELX=Oj.cell[0], GMAPLEVELY=Oj.cell[1])
            Wj._track_update(nowj)
            if k == 3: Wj.walk_to(ax_ + 4, ay_ + 4); Wj.walk_task["next"] = nowj
            if Wj.walking_to(): Wj._walk_tick(nowj)
            if k >= 3: a_, b_ = Wj._gpos(), Oj._gpos(); mind = min(mind, max(abs(a_[0] - b_[0]), abs(a_[1] - b_[1])))
        return mind
    res_j = {m: [jitter_run(m, s) for s in range(25)] for m in ("aware", "static", "blind")}
    ov = {m: sum(1 for v in vs if v < 16) for m, vs in res_j.items()}; mean = {m: sum(vs) / len(vs) for m, vs in res_j.items()}
    check(ov["aware"] == 0 and mean["aware"] >= mean["static"] - 1, f"with jittery updates prediction is never worse than avoiding the current position: overlaps {ov}, mean closest {mean}")
    check(ov["blind"] > 0, f"without turn tracking the same jittery scenario overlaps ({ov['blind']} of 25), which is why the heading follows turns")
    print("walk tests passed")

if __name__ == "__main__": main()
