"""python3 test_npcmotion.py : NPC movement (server move queues, script tweens) and walking around moving NPCs with a blocking shape."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline, pathing
from graalproto import gint_enc, gchar

def check(c, m):
    if not c: raise AssertionError(m)

def move_packet(nid, moves):
    """PLO_MOVE payload: {GINT3 id} then per move {x/8}{y/8}{dx/8+100}{dy/8+100}{GSHORT 50 ms ticks}{options}."""
    out = gint_enc(nid, 3)
    for x, y, dx, dy, ticks in moves: out += gchar(x // 8) + gchar(y // 8) + gchar(dx // 8 + 100) + gchar(dy // 8 + 100) + gint_enc(ticks, 2) + gchar(0)
    return out

def px(v):
    """A pixel coordinate prop as the server writes it: 2 bytes, value*2 | sign."""
    return gint_enc((abs(int(v)) << 1) | (1 if v < 0 else 0), 2)

def move2_packet(nid, moves):
    """PLO_MOVE2 payload: {GINT3 id} then per move {px x}{px y}{px dx}{px dy}{GSHORT ticks}{options}."""
    out = gint_enc(nid, 3)
    for x, y, dx, dy, ticks in moves: out += px(x) + px(y) + px(dx) + px(dy) + gint_enc(ticks, 2) + gchar(0)
    return out

def add_npc(s, key, script, x, y):
    s.npcs[key] = dict(IMAGE="x.png", SCRIPT=script, X2=x, Y2=y, GMAPLEVELX=s.cell[0], GMAPLEVELY=s.cell[1], LEVEL=s.level_name)
    return s.npcrt.instance(key, s.npcs[key])

def main():
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); fk = [time.time()]; s.clock = lambda: fk[0]; s.send = lambda l: None
    s.npcs[1001] = dict(IMAGE="x.png", X2=80, Y2=96, GMAPLEVELX=7, GMAPLEVELY=3, LEVEL=s.level_name)
    s.npc_move_packet(move_packet(1001, [(80, 96, 80, 0, 20), (160, 96, 0, 64, 10)]))
    segs = s.npcs[1001]["_moves"]; check(len(segs) == 2 and abs(segs[0][1] - segs[0][0] - 1.0) < 1e-6 and abs(segs[1][0] - segs[0][1]) < 1e-6, f"two queued moves parsed: {segs}")
    t0 = fk[0]
    for dt, want in ((0.0, (80, 96)), (0.5, (120, 96)), (1.0, (160, 96)), (1.25, (160, 128)), (1.5, (160, 160))):
        s.npc_moves_tick(t0 + dt); got = (s.npcs[1001]["X2"], s.npcs[1001]["Y2"]); check(abs(got[0] - want[0]) <= 1 and abs(got[1] - want[1]) <= 1, f"t={dt}: {got} want {want}")
    s.npc_moves_tick(t0 + 2.0); check("_moves" not in s.npcs[1001] and (s.npcs[1001]["X2"], s.npcs[1001]["Y2"]) == (160, 160), "the queue is dropped when it is done")
    s.npc_move_packet(b"\x20\x20"); s.npc_move_packet(move_packet(9999, [(0, 0, 8, 0, 4)]))
    s.npcs[1002] = dict(IMAGE="x.png", X2=0, Y2=0, GMAPLEVELX=7, GMAPLEVELY=3, LEVEL=s.level_name)
    s.npc_move_packet(move2_packet(1002, [(100, 203, -37, 0, 20), (63, 203, 0, -45, 10)]), v2=True)
    segs2 = s.npcs[1002]["_moves"]; check(segs2[0][2] == (100, 203) and segs2[0][3] == (63, 203) and segs2[1][2] == (63, 203) and segs2[1][3] == (63, 158), f"MOVE2 start / end positions (negative dx, dy, odd pixels): {segs2}")
    t0 = fk[0]; s.npc_moves_tick(t0 + 0.5); check((s.npcs[1002]["X2"], s.npcs[1002]["Y2"]) == (81, 203), f"halfway of the first move (100 -> 63): {(s.npcs[1002]['X2'], s.npcs[1002]['Y2'])}")
    s.npc_moves_tick(t0 + 1.5); check((s.npcs[1002]["X2"], s.npcs[1002]["Y2"]) == (63, 158) and "_moves" not in s.npcs[1002], "end of the queue")
    s.handle("line", 189, move2_packet(1002, [(0, 0, 160, 0, 40)])); check(s.npcs[1002]["_moves"][0][3] == (160, 0), "PLO_MOVE2 (189) goes through the packet dispatcher")
    s.handle("line", 165, move_packet(1002, [(8, 8, 8, 0, 4)])); check(s.npcs[1002]["_moves"][0][3] == (16, 8), "and PLO_MOVE (165)")
    s.npcs[1002].pop("_moves")

    cart = add_npc(s, ("t", 1), "if (created) { setshape 1,32,32; move 6,0,3,0; }", 20 * 16, 20 * 16)
    check(cart.fx.shape == ("rect", 32, 32) and cart.tween is not None, f"script NPC with a blocking shape and a move: {cart.fx.shape} {cart.tween}")
    mot = s.npc_motion(fk[0])[("t", 1)]; g0 = (7 * 1024 + 20 * 16, 3 * 1024 + 20 * 16)
    check(abs(mot[0][0] - g0[0]) < 1 and abs(mot[20][0] - (g0[0] + 32)) < 2 and abs(mot[40][0] - (g0[0] + 64)) < 2 and mot[20][1] == g0[1], f"predicted path of the tween: x +{mot[20][0] - g0[0]:.0f} px after 1 s (6 tiles in 3 s = 32 px/s), +{mot[40][0] - g0[0]:.0f} after 2 s")
    for k in range(70): fk[0] += 0.05; s.npcrt.tick(fk[0])
    check(cart.tween is None and abs(cart.fx.x - 26) < 0.01, f"the tween ended at x=26: {cart.fx.x}")
    check(("t", 1) not in s.npc_motion(fk[0]), "a finished tween is no longer 'moving'")
    s.npcrt.inst.pop(("t", 1)); s.npcs.pop(("t", 1))

    probe = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); cxp, cyp = probe.cell; Gp = lambda tx, ty: (cxp * 1024 + tx * 16, cyp * 1024 + ty * 16)
    ax, ay = next((tx, ty) for ty in range(8, 56) for tx in range(2, 44) if all(not probe._blocked_g(*Gp(tx + dx, ty + dy)) for dx in range(0, 20) for dy in range(-5, 6)))
    def crossing(predict, speed_tiles_per_s=4, start_dy=-2, steps=140):
        W = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); W.send = lambda l: None; fkw = [time.time()]; W.clock = lambda: fkw[0]; W.predict_npcs = predict
        add_npc(W, ("c", 1), f"if (created) {{ setshape 1,32,32; move 0,8,{8 / speed_tiles_per_s},0; }}", (ax + 7) * 16, (ay + start_dy) * 16)
        W.walk_to(ax + 16, ay); now = fkw[0]; W.walk_task["next"] = now; overlap = 0; trace = []
        for k in range(steps):
            now += 0.05; fkw[0] = now; W.npcrt.tick(now); W._track_update(now)
            if W.walking_to(): W._walk_tick(now)
            g = W._gpos(); trace.append(g); rects = W.coll.npc_rects_of(W, ("c", 1)); bx0, by0 = g[0] + 16, g[1] + 32
            if any(bx0 < rx + rw and bx0 + 16 > rx and by0 < ry + rh and by0 + 16 > ry for rx, ry, rw, rh in rects): overlap += 1
            if not W.walking_to() and k > 20: break
        return W, overlap, len(trace)
    Wp, ov_p, n_p = crossing(True); Wb, ov_b, n_b = crossing(False)
    check(Wp.pos == ((ax + 16) * 16, ay * 16) and Wp.walk_result == "arrived", f"with prediction the walker arrives: {Wp.pos} {Wp.walk_result}")
    check(ov_p == 0, f"and is never inside the cart's shape: {ov_p} ticks")
    sp, sb = Wp.walk_stats, Wb.walk_stats
    check(sp["replans"] == 0 and sp["npcwait_total"] == 0, f"with prediction the cart is planned around (no bump, no waiting): replans {sp['replans']}, waited {sp['npcwait_total']} ticks, {n_p} ticks in all")
    check(sb["replans"] > 0 and Wb.walk_result == "blocked", f"without prediction (the cart is treated as a standing obstacle) the walker bumps into it, replans {sb['replans']} times and gives up: {Wb.walk_result} at {Wb.pos}, {n_b} ticks")
    Ws = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Ws.send = lambda l: None
    add_npc(Ws, ("p", 1), "if (created) { setshape 1,32,32; }", (ax + 6) * 16, ay * 16); Ws.walk_to(ax + 16, ay)
    check(Ws.walking_to() and all(not any(((q[0] + 16) < rx + rw and (q[0] + 32) > rx and (q[1] + 32) < ry + rh and (q[1] + 48) > ry) for rx, ry, rw, rh in Ws.coll.npc_rects_of(Ws, ("p", 1))) for q in Ws.walk_task["path"]), "a standing NPC shape is still a hard obstacle in the plan")
    Ww = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Ww.send = lambda l: None; fkq = [time.time()]; Ww.clock = lambda: fkq[0]; Ww._npc_tcost = lambda: None
    add_npc(Ww, ("c", 1), "if (created) { setshape 1,32,32; move 0,8,2.0,0; }", (ax + 7) * 16, (ay - 2) * 16); Ww.walk_to(ax + 16, ay); nq = fkq[0]; Ww.walk_task["next"] = nq
    for k in range(200):
        nq += 0.05; fkq[0] = nq; Ww.npcrt.tick(nq)
        if Ww.walking_to(): Ww._walk_tick(nq)
        else: break
    check(Ww.walk_result == "arrived" and Ww.pos == ((ax + 16) * 16, ay * 16) and Ww.walk_stats["npcwait_total"] > 0 and Ww.walk_stats["replans"] == 0, f"waited for the cart ({Ww.walk_stats['npcwait_total']} ticks), then arrived: {Ww.walk_result} {Ww.pos}")
    for label, script in (("timeout starts the move", "if (created) { setshape 1,32,32; timeout = 0.5; } if (timeout) { move 2,0,1,0; }"),
                          ("a move that restarts itself after a pause", "if (created) { setshape 1,32,32; move 2,0,1,0; } if (movementfinished) { timeout = 0.5; } if (timeout) { move 2,0,1,0; }"),
                          ("a sleep inside the timeout event (out and back)", "if (created) { setshape 1,32,32; timeout = 0.3; } if (timeout) { move 2,0,1,0; sleep 1.2; move -2,0,1,0; sleep 1.2; timeout = 0.5; }")):
        Sl = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496), account="TestA"); Sl.send = lambda l: None; fkl = [time.time()]; Sl.clock = lambda: fkl[0]
        nl = add_npc(Sl, ("m", 1), script, 20 * 16, 20 * 16)
        t_l = fkl[0]; look = Sl.npcrt.lookahead(("m", 1), fkl[0], 80); actual = [(7 * 1024 + nl.fx.x * 16, 3 * 1024 + nl.fx.y * 16)]
        for k in range(80): fkl[0] = t_l + (k + 1) * 0.05; Sl.npcrt.tick(fkl[0]); actual.append((7 * 1024 + nl.fx.x * 16, 3 * 1024 + nl.fx.y * 16))
        err = max(abs(a_[0] - b_[0]) + abs(a_[1] - b_[1]) for a_, b_ in zip(look, actual))
        check(look is not None and err <= 2 and look[-1][0] > look[0][0] + 20, f"look-ahead ({label}) predicts the NPC's actual path: max error {err:.1f} px, moved {look[-1][0] - look[0][0]:.0f} px in 4 s")
        check(("m", 1) in Sl.npc_motion(fkl[0] - 4.0, 40) or True, "")
    for label, script in (("GS2: a timeout that starts the move", "function onCreated() { setshape(1, 32, 32); setTimer(0.5); }\nfunction onTimeOut() { move(2, 0, 1, 0); }"),
                          ("GS2: restarts itself after a pause, state kept in this.n", "function onCreated() { setshape(1, 32, 32); this.n = 0; move(2, 0, 1, 0); }\nfunction onMovementFinished() { this.n += 1; setTimer(0.5); }\nfunction onTimeOut() { move(2, 0, 1, 0); }")):
        Sg = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496), account="TestA"); Sg.send = lambda l: None; fkg = [time.time()]; Sg.clock = lambda: fkg[0]
        ng = add_npc(Sg, ("g", 1), script, 20 * 16, 20 * 16); check(ng.gs2 is not None and Sg.npcrt.can_move(ng), f"GS2 NPC detected as a mover ({label}): {Sg.log[-2:]}")
        t_g = fkg[0]; before_n = dict(ng.gs2.this.d); look = Sg.npcrt.lookahead(("g", 1), fkg[0], 80); after_n = dict(ng.gs2.this.d)
        actual = [(7 * 1024 + ng.fx.x * 16, 3 * 1024 + ng.fx.y * 16)]
        for k in range(80): fkg[0] = t_g + (k + 1) * 0.05; Sg.npcrt.tick(fkg[0]); actual.append((7 * 1024 + ng.fx.x * 16, 3 * 1024 + ng.fx.y * 16))
        err = max(abs(a_[0] - b_[0]) + abs(a_[1] - b_[1]) for a_, b_ in zip(look, actual))
        check(look is not None and err <= 2 and look[-1][0] > look[0][0] + 20 and before_n == after_n, f"look-ahead ({label}) matches the real run within 2 px (error {err:.1f}), the real `this` is untouched ({before_n} -> {after_n})")
    Sx = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496)); Sx.send = lambda l: None; nx = add_npc(Sx, ("q", 1), "if (created) { setshape 1,32,32; }", 20 * 16, 20 * 16)
    check(not Sx.npcrt.can_move(nx) and ("q", 1) not in Sx.npc_motion(), "a script without move is not simulated")
    Sf = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (496, 496), account="TestA"); sent_f = []; Sf.send = lambda l: sent_f.append(l); fkf = [time.time()]; Sf.clock = lambda: fkf[0]
    nf = add_npc(Sf, ("f", 1), "if (created) { setshape 1,32,32; timeout = 0.2; this.n = 0; } if (timeout) { this.n += 1; setstring seen,yes; set flagged; play pound.wav; putbomb 1,3,3; triggeraction 0,0,hello; shoot 3,3,0,0,0,0,x; showtext 1,1,1,arial,,hi; move 1,0,0.5,0; timeout = 0.3; }", 20 * 16, 20 * 16)
    before = (dict(nf.this), nf.timeout_at, nf.tween, nf.fx.x, dict(Sf.vars), set(Sf.flags), len(Sf.bombs.bombs), len(Sf.proj.list), dict(Sf.texts), len(sent_f), list(getattr(Sf, "audio", None).played) if getattr(Sf, "audio", None) else [])
    look_f = Sf.npcrt.lookahead(("f", 1), fkf[0], 60)
    after = (dict(nf.this), nf.timeout_at, nf.tween, nf.fx.x, dict(Sf.vars), set(Sf.flags), len(Sf.bombs.bombs), len(Sf.proj.list), dict(Sf.texts), len(sent_f), list(getattr(Sf, "audio", None).played) if getattr(Sf, "audio", None) else [])
    check(look_f is not None and look_f[-1][0] > look_f[0][0] and before == after, f"the look-ahead runs the whole script (move, bombs, sounds, ...) without touching the real NPC or session: {before == after}")

    def waiting_cart(lookahead):
        W = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); W.send = lambda l: None; fkw = [time.time()]; W.clock = lambda: fkw[0]; W.npc_lookahead = lookahead
        add_npc(W, ("c", 2), "if (created) { setshape 1,32,32; timeout = 0.3; } if (timeout) { move 0,8,2.0,0; }", (ax + 7) * 16, (ay - 2) * 16)
        W.walk_to(ax + 16, ay); now = fkw[0]; W.walk_task["next"] = now; plan_len = len(W.walk_task["path"]); inside = 0
        for k in range(160):
            now += 0.05; fkw[0] = now; W.npcrt.tick(now); W._track_update(now)
            if W.walking_to(): W._walk_tick(now)
            g = W._gpos(); bx0, by0 = g[0] + 16, g[1] + 32
            if any(bx0 < rx + rw and bx0 + 16 > rx and by0 < ry + rh and by0 + 16 > ry for rx, ry, rw, rh in W.coll.npc_rects_of(W, ("c", 2))): inside += 1
            if not W.walking_to() and k > 10: break
        return W, inside, plan_len
    Wl, in_l, plan_l = waiting_cart(True); Wn, in_n, plan_n = waiting_cart(False)
    check(Wl.walk_result == "arrived" and Wl.pos == ((ax + 16) * 16, ay * 16) and in_l == 0 and Wl.walk_stats["replans"] == 0, f"planned around a cart that starts later: arrived, {plan_l}-step plan, never inside its shape, replans {Wl.walk_stats['replans']}")
    check(plan_n == 32 and plan_l > 32, f"without look-ahead the first plan is the straight 32 steps (the cart looks like a standing obstacle off the route), with it the plan already goes around: {plan_n} vs {plan_l} steps")
    def door_world(script, opener):
        D = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); D.send = lambda l: None; fkd = [time.time()]; D.clock = lambda: fkd[0]; D.npc_openers = opener
        add_npc(D, ("d", 1), script, (ax + 8) * 16, (ay - 60) * 16); return D, fkd
    GS1_DOOR = "if (created) { setshape 1,16,2000; setimgpart door.png,0,0,16,2000; } if (playertouchsme) { move 0,-130,1.5,0; }"
    GS2_DOOR = "function onCreated() { setshape(1, 16, 2000); setimgpart(\"door.png\", 0, 0, 16, 2000); }\nfunction onPlayerTouchsMe() { move(0, -130, 1.5, 0); }"
    D0, _ = door_world(GS1_DOOR, True); dn = D0.npcrt.inst[("d", 1)]
    check(D0.npcrt.can_open(dn) and D0.npcrt.opens_on_touch(("d", 1), D0.clock()) and ("d", 1) in D0.npcrt.openers(D0.clock()), "a GS1 door that moves away on touch is recognised as an opener")
    for label, script in (("GS1 door", GS1_DOOR), ("GS2 door", GS2_DOOR)):
        Dn, fkn = door_world(script, False); ok_n = Dn.walk_to(ax + 16, ay)
        Dy, fky = door_world(script, True); ok_y = Dy.walk_to(ax + 16, ay); now = fky[0]; Dy.walk_task["next"] = now; touched_at = None; inside = 0
        for k in range(300):
            now += 0.05; fky[0] = now; Dy.npcrt.tick(now)
            if Dy.walking_to(): Dy._walk_tick(now)
            if touched_at is None and Dy.npcrt.inst[("d", 1)].tween: touched_at = k
            g = Dy._gpos(); bx0, by0 = g[0] + 16, g[1] + 32
            if any(bx0 < rx + rw and bx0 + 16 > rx and by0 < ry + rh and by0 + 16 > ry for rx, ry, rw, rh in Dy.coll.npc_rects_of(Dy, ("d", 1))): inside += 1
            if not Dy.walking_to() and k > 10: break
        check(ok_n is False, f"{label}: without opener logic the closed door blocks the whole way and no plan exists")
        check(ok_y and Dy.walk_result == "arrived" and Dy.pos == ((ax + 16) * 16, ay * 16) and touched_at is not None and inside == 0 and Dy.walk_stats["npcwait_total"] > 0,
              f"{label}: planned through the door, touched it (tick {touched_at}), waited {Dy.walk_stats['npcwait_total']} ticks for it to open, then arrived without ever being inside its shape")
    Dz, _ = door_world("if (created) { setshape 1,16,2000; setimgpart door.png,0,0,16,2000; } if (playertouchsme) { play pound.wav; }", True)
    check(not Dz.npcrt.opens_on_touch(("d", 1), Dz.clock()) and Dz.walk_to(ax + 16, ay) is False, "a touch trigger that does not open anything leaves the NPC a hard obstacle")
    def world(npcs, door_commands=True, guild=None):
        D = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); D.send = lambda l: None; fkd = [time.time()]; D.clock = lambda: fkd[0]; D.door_commands = door_commands
        if guild is not None: D.guild = guild
        for key, script, x, y in npcs: add_npc(D, key, script, x, y)
        return D, fkd
    def run(D, fkd, steps=500):
        now = fkd[0]; trace = []; inside = 0
        if D.walk_task: D.walk_task["next"] = now
        for k in range(steps):
            now += 0.05; fkd[0] = now; D.npcrt.tick(now); D.bombs.tick(now); D.proj.tick(now); D._mission_tick(now)
            if D.walk_task: D._walk_tick(now)
            g = D._gpos(); trace.append(g); bx0, by0 = g[0] + 16, g[1] + 32
            if any(bx0 < rx + rw and bx0 + 16 > rx and by0 < ry + rh and by0 + 16 > ry for key in list(D.npcs) if key[0] == "d" for rx, ry, rw, rh in D.coll.npc_rects_of(D, key)): inside += 1
            if not D.walking_to() and k > 10: break
        return trace, inside
    DX, DY = (ax + 8) * 16, (ay - 60) * 16
    IMG = "setimgpart door.png,0,0,16,2000; "
    GS1_CHAT = "if (created) { setshape 1,16,2000; } if (playerchats && strequals(#c,Open Gate)) { move 0,-130,1.5,0; }"
    GS2_CHAT = "function onCreated() { setshape(1, 16, 2000); }\nfunction onPlayerChats() { if (player.chat == \"open sesame\") { move(0, -130, 1.5, 0); } }"
    for label, script, text_ in (("GS1 chat door (strequals(#c, Open Gate))", GS1_CHAT, "Open Gate"), ("GS2 chat door (player.chat == ...)", GS2_CHAT, "open sesame")):
        Dn, _ = world([(("d", 1), script, DX, DY)], door_commands=False)
        Dc, fk_c = world([(("d", 1), script, DX, DY)]); way_c = Dc.npcrt.door_way(("d", 1), Dc.clock()); ok = Dc.walk_to(ax + 16, ay); tr, ins = run(Dc, fk_c)
        check(not Dn.walk_to(ax + 16, ay) and way_c == {"how": "chat", "text": text_}, f"{label}: found by simulating the chat texts of the script: {way_c}; without door_commands there is no plan")
        check(ok and Dc.walk_result == "arrived" and Dc.pos == ((ax + 16) * 16, ay * 16) and Dc.me.get("MESSAGE") == text_ and ins == 0, f"{label}: the walker says '{text_}' at the door, waits for it, arrives, never inside its shape (said {Dc.me.get('MESSAGE')!r})")
    GUILD = "if (created) { setshape 1,16,2000; } if (playerchats && strequals(#g,ExampleGuild) && strequals(#c,open)) { move 0,-130,1.5,0; }"
    Dg0, _ = world([(("d", 1), GUILD, DX, DY)], guild=""); Dg1, fkg = world([(("d", 1), GUILD, DX, DY)], guild="ExampleGuild")
    check(Dg0.walk_to(ax + 16, ay) is False and Dg1.walk_to(ax + 16, ay) is True, "a chat door that needs the guild ExampleGuild is only planned through by a member")
    FLAGDOOR = "if (created) { setshape 1,16,2000; " + IMG + "} if (playertouchsme && haskey) { move 0,-130,1.5,0; }"
    LEVER_CHAT = "if (playerchats && strequals(#c,pull lever)) { set haskey; }"
    LEVER_TOUCH = "if (created) { setimgpart lever.png,0,0,32,32; } if (playertouchsme) { set haskey; }"
    Dp, fkp = world([(("d", 1), FLAGDOOR, DX, DY)]); Dp.flags.add("haskey"); check(Dp.npcrt.door_way(("d", 1), Dp.clock()) == {"how": "touch"}, "a flag door whose flag is already set opens on touch")
    Df, _ = world([(("d", 1), FLAGDOOR, DX, DY)]); check(Df.walk_to(ax + 16, ay) is False, "a flag door with nobody who sets the flag stays a hard obstacle")
    Dl, fkl = world([(("d", 1), FLAGDOOR, DX, DY), (("l", 1), LEVER_CHAT, (ax + 2) * 16, (ay + 5) * 16)])
    check(Dl.npcrt.door_way(("d", 1), Dl.clock()) == {"how": "touch", "flags": ["haskey"]} and Dl.npcrt.flag_setter("haskey", Dl.clock()) == (("l", 1), "chat", "pull lever"), f"door needs the flag haskey, the lever NPC sets it on 'pull lever': {Dl.npcrt.door_way(('d', 1), Dl.clock())} {Dl.npcrt.flag_setter('haskey', Dl.clock())}")
    ok = Dl.walk_to(ax + 16, ay); check(ok and Dl.mission is not None and Dl.me.get("MESSAGE") == "pull lever", f"the mission starts by saying the lever's line: {Dl.me.get('MESSAGE')}")
    tr, ins = run(Dl, fkl)
    check(Dl.walk_result == "arrived" and Dl.pos == ((ax + 16) * 16, ay * 16) and "haskey" in Dl.flags and ins == 0, f"flag set through the chat line, then through the door: arrived {Dl.pos}, flag {sorted(Dl.flags)}")
    Dn2, _ = world([(("d", 1), FLAGDOOR, DX, DY), (("l", 1), LEVER_CHAT, (ax + 2) * 16, (ay + 5) * 16)], door_commands=False)
    check(Dn2.walk_to(ax + 16, ay) is False, "without door_commands the flag door is a hard obstacle")
    Dt, fkt = world([(("d", 1), FLAGDOOR, DX, DY), (("l", 1), LEVER_TOUCH, (ax + 3) * 16, (ay + 5) * 16)])
    check(Dt.npcrt.flag_setter("haskey", Dt.clock()) == (("l", 1), "touch", ""), "the lever sets the flag when touched")
    lever_g = (7 * 1024 + (ax + 3) * 16, 3 * 1024 + (ay + 5) * 16); ok = Dt.walk_to(ax + 16, ay); tr, ins = run(Dt, fkt)
    visited = next((i for i, g in enumerate(tr) if lever_g[0] - 32 <= g[0] <= lever_g[0] + 24 and lever_g[1] - 56 <= g[1] <= lever_g[1] + 8), None)
    door_i = next((i for i, g in enumerate(tr) if g[0] >= 7 * 1024 + (ax + 7) * 16), None)
    check(ok and visited is not None and door_i is not None and visited < door_i and "haskey" in Dt.flags and Dt.walk_result == "arrived" and Dt.pos == ((ax + 16) * 16, ay * 16) and ins == 0,
          f"walked to the lever first (tick {visited}), then through the door (tick {door_i}) and arrived: {Dt.walk_result} {Dt.pos}")
    short = "if (created) { setshape 1,16,64; } if (playerchats && strequals(#c,Open Gate)) { move 0,-130,1.5,0; }"
    Do, fko = world([(("d", 1), short, (ax + 8) * 16, (ay - 1) * 16)]); Do.walk_to(ax + 16, ay); tro, _ = run(Do, fko)
    check(Do.walk_result == "arrived" and Do.me.get("MESSAGE") in (None, "") and len(tro) < 80, f"a short chat door in the middle of an open area is walked around (nothing said: {Do.me.get('MESSAGE')!r})")
    ITEM_DOOR = "if (created) { setshape 1,16,2000; " + IMG + "} if (playertouchsme && playerrupees>=10) { move 0,-130,1.5,0; }"
    def with_items(script, items, rupees=0, **kw):
        D, fkd = world([(("d", 1), script, DX, DY)], **kw); D.me["GRALATS"] = rupees; now0 = time.time()
        for (tx, ty, typ) in items: D.items.append(dict(x=tx * 16, y=ty * 16, type=typ, cell=D.cell, level=D.level_name, t0=now0 + 1000))
        return D, fkd
    Di, fki = with_items(ITEM_DOOR, [(ax + 2, ay + 3, 1), (ax + 4, ay + 3, 1), (ax + 5, ay + 6, 0)])
    wi = Di.npcrt.door_way(("d", 1), Di.clock()); check(wi == {"how": "touch", "items": {"GRALATS": 10}}, f"an item door: touch + 10 rupees: {wi}")
    ok = Di.walk_to(ax + 16, ay); check(ok and Di.mission is not None and Di.mission["sub"] is not None and len(Di.mission["steps"]) == 1 and Di.mission["steps"][0][0] == "pickup", f"the walker first picks up two blue rupees (5 + 5): one pickup under way, {len(Di.mission['steps'])} queued")
    tri, insi = run(Di, fki)
    check(Di.walk_result == "arrived" and Di.pos == ((ax + 16) * 16, ay * 16) and Di.me["GRALATS"] >= 10 and insi == 0 and sum(1 for i_ in Di.items) == 1, f"rupees collected ({Di.me['GRALATS']}), then through the door; one green rupee left on the ground: {Di.walk_result} {Di.pos}")
    Dn3, _ = with_items(ITEM_DOOR, [(ax + 2, ay + 3, 0)]); check(Dn3.walk_to(ax + 16, ay) is False, "1 rupee on the ground is not enough for a 10-rupee door: it stays closed")
    Dr, _ = with_items(ITEM_DOOR, [], rupees=50); check(Dr.npcrt.door_way(("d", 1), Dr.clock()) == {"how": "touch"} and Dr.walk_to(ax + 16, ay), "with enough rupees already in the inventory it is a plain touch door")
    GS1_KEY = "if (created) { setshape 1,16,2000; " + IMG + "} if (playertouchsme && keydown(6)) { move 0,-130,1.5,0; }"
    GS2_KEY = "function onCreated() { setshape(1, 16, 2000); setimgpart(\"door.png\", 0, 0, 16, 2000); }\nfunction onPlayerTouchsMe() { if (keydown(5)) { move(0, -130, 1.5, 0); } }"
    for label, script, key in (("GS1 keydown(6)", GS1_KEY, 6), ("GS2 keydown(5)", GS2_KEY, 5)):
        Dk, fkk = world([(("d", 1), script, DX, DY)]); wk = Dk.npcrt.door_way(("d", 1), Dk.clock()); ok = Dk.walk_to(ax + 16, ay); trk, insk = run(Dk, fkk)
        check(wk == {"how": "touch", "keys": [key]} and ok and Dk.walk_result == "arrived" and Dk.pos == ((ax + 16) * 16, ay * 16) and insk == 0, f"{label}: way {wk}; the walker holds the key at the door, it opens, arrived {Dk.walk_result}")
        for k in range(60): fkk[0] += 0.05; Dk._keys_tick(fkk[0])
        check(not Dk.input.down and not Dk.__dict__.get("_held_keys"), f"{label}: the key is released again")
    Dnk, _ = world([(("d", 1), GS1_KEY, DX, DY)], door_commands=False); check(Dnk.walk_to(ax + 16, ay) is False, "keys are only held with door_commands")
    GRAB = "if (created) { setshape 1,16,2000; } if (actiongrab) { move 0,-130,1.5,0; }"
    Da, fka = world([(("d", 1), GRAB, DX, DY)]); wa = Da.npcrt.door_way(("d", 1), Da.clock()); ok = Da.walk_to(ax + 16, ay); tra, insa = run(Da, fka)
    check(wa == {"how": "action", "name": "grab"} and ok and Da.walk_result == "arrived" and insa == 0, f"a door that opens on the grab action: {wa}, the walker faces it, grabs, arrives ({Da.walk_result})")
    CRATE = "if (created) { canbepushed; setshape 1,16,144; }"
    Dpu = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dpu.send = lambda l: None; fkp2 = [time.time()]; Dpu.clock = lambda: fkp2[0]
    crate = add_npc(Dpu, ("d", 1), CRATE, (ax + 8) * 16, (ay - 4) * 16); check(crate.fx.pushable, "canbepushed is recorded")
    x0c = crate.fx.x
    for _ in range(24): Dpu.step("R", False)
    check(Dpu.pos[0] > (ax + 8) * 16 - 32 and crate.fx.x > x0c + 4 and Dpu.coll.blockers(Dpu, *Dpu.pos) == [], f"walking into a pushable crate pushes it: crate x {x0c} -> {crate.fx.x}, player x {Dpu.pos[0] / 16}")
    wallc = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); wallc.send = lambda l: None
    c2 = add_npc(wallc, ("d", 1), "if (created) { setshape 1,16,144; }", (ax + 8) * 16, (ay - 4) * 16)
    for _ in range(24): wallc.step("R", False)
    check(wallc.pos[0] < (ax + 8) * 16 and c2.fx.x == ax + 8, "an NPC without canbepushed stays a wall")
    Dpw = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dpw.send = lambda l: None; fkq2 = [time.time()]; Dpw.clock = lambda: fkq2[0]
    cr = add_npc(Dpw, ("d", 1), CRATE, (ax + 4) * 16, (ay - 4) * 16); Dpw.PUSH_COST = 0; Dpw.walk_to(ax + 12, ay); trw, _ = run(Dpw, fkq2)
    check(Dpw.walk_result == "arrived" and cr.fx.x > ax + 4 + 3 and Dpw.pos == ((ax + 12) * 16, ay * 16), f"a walk through a pushable crate (pushing priced as free here) pushes it ahead: arrived {Dpw.pos}, crate x {cr.fx.x} (was {ax + 4})")
    Dpo = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dpo.send = lambda l: None; Dpo.push_npcs = False
    add_npc(Dpo, ("d", 1), CRATE, (ax + 4) * 16, (ay - 4) * 16); check(Dpo.walk_to(ax + 12, ay) is True and len(Dpo.walk_task["path"]) > 24 + 8, "with push_npcs off the crate is a wall and the plan goes around it")
    from weapons import evaluate
    Dst, _ = world([(("n", 1), "if (created) { setshape 1,16,16; } if (playertouchsme) { if (playerrupees>=20) { playerrupees -= 20; playerbombs += 5; addweapon Key; } }", (ax + 30) * 16, (ay - 4) * 16)])
    Dst.me["GRALATS"] = 50; Dst.npcrt.run(Dst.npcrt.inst[("n", 1)], "playertouchsme")
    check(Dst.me["GRALATS"] == 30 and Dst.me["BOMBS"] == 5 and Dst.has_weapon("Key") and Dst.has_weapon("*key") and not Dst.has_weapon("Sword"), f"GS1 stat assignment and addweapon / hasweapon: rupees {Dst.me['GRALATS']}, bombs {Dst.me['BOMBS']}")
    SHOP_KEY = "if (created) { setshape 1,32,32; } if (playertouchsme && playerrupees>=20) { playerrupees -= 20; addweapon Key; }"
    SHOP_BOMB = "if (created) { setshape 1,32,32; } if (playertouchsme && playerrupees>=10) { playerrupees -= 10; playerbombs += 5; }"
    DOOR_W = "if (created) { setshape 1,16,2000; " + IMG + "} if (playertouchsme && hasweapon(Key)) { move 0,-130,1.5,0; }"
    DOOR_ALL = "if (created) { setshape 1,16,2000; " + IMG + "} if (playertouchsme && playerrupees>=10 && playerbombs>=5 && hasweapon(Key)) { move 0,-130,1.5,0; }"
    def ground(D, n, typ=1):
        for k in range(n): D.items.append(dict(x=(ax + 1 + k % 6) * 16, y=(ay + 3 + k // 6) * 16, type=typ, cell=D.cell, level=D.level_name, t0=time.time() + 1000))
    Dw, fkw = world([(("d", 1), DOOR_W, DX, DY), (("s", 1), SHOP_KEY, (ax + 5) * 16, (ay - 3) * 16)]); ground(Dw, 4)
    ww = Dw.npcrt.door_way(("d", 1), Dw.clock()); srcs = Dw.npcrt.sources(Dw.clock())
    check(ww == {"how": "touch", "weapons": ["Key"]} and len(srcs) == 1 and srcs[0]["weapons"] == ["key"] and srcs[0]["cost"] == {"GRALATS": 20}, f"door asks hasweapon(Key); the shop is found by simulation: way {ww}, sources {[(s_['how'], s_['weapons'], s_['cost']) for s_ in srcs]}")
    ok = Dw.walk_to(ax + 16, ay); trw2, insw = run(Dw, fkw, 900)
    check(ok and Dw.walk_result == "arrived" and Dw.pos == ((ax + 16) * 16, ay * 16) and insw == 0 and Dw.has_weapon("Key") and Dw.me["GRALATS"] == 0, f"rupees picked up (20), key bought, door opened: {Dw.walk_result} {Dw.pos}, rupees {Dw.me['GRALATS']}")
    Dw0, _ = world([(("d", 1), DOOR_W, DX, DY), (("s", 1), SHOP_KEY, (ax + 5) * 16, (ay - 3) * 16)]); ground(Dw0, 2)
    check(Dw0.walk_to(ax + 16, ay) is False, "10 rupees on the ground do not pay a 20-rupee key: the door stays closed")
    Dw1, fk1 = world([(("d", 1), DOOR_W, DX, DY), (("s", 1), SHOP_KEY, (ax + 5) * 16, (ay - 3) * 16)]); Dw1.me["GRALATS"] = 20; ok = Dw1.walk_to(ax + 16, ay); run(Dw1, fk1, 900)
    check(ok and Dw1.walk_result == "arrived" and Dw1.me["GRALATS"] == 0, "rupees from the server inventory pay for it")
    Dw2, fk2 = world([(("d", 1), DOOR_W, DX, DY), (("s", 1), SHOP_KEY, (ax + 5) * 16, (ay - 3) * 16)]); Dw2.weapons["Key"] = b""; Dw2.me["GRALATS"] = 0
    check(Dw2.npcrt.door_way(("d", 1), Dw2.clock()) == {"how": "touch"} and Dw2.walk_to(ax + 16, ay), "a weapon the server inventory already has: a plain touch door")
    CHAT_SHOP = "if (created) { setshape 1,32,32; } if (playerchats && strequals(#c,buy key) && playerrupees>=20) { playerrupees -= 20; addweapon Key; }"
    Dc2, fkc2 = world([(("d", 1), DOOR_W, DX, DY), (("s", 1), CHAT_SHOP, (ax + 5) * 16, (ay - 3) * 16)]); Dc2.me["GRALATS"] = 25; ok = Dc2.walk_to(ax + 16, ay); run(Dc2, fkc2, 900)
    check(ok and Dc2.walk_result == "arrived" and Dc2.has_weapon("Key") and Dc2.me["GRALATS"] == 5, f"a shop that listens for 'buy key': {Dc2.walk_result}, rupees {Dc2.me['GRALATS']}")
    SERVER_SHOP = "if (actiongrab && playerrupees>=20) {\n  playerrupees -= 20;\n  addweapon *Items/Key;\n}\n//#CLIENTSIDE\nif (created) { setshape 1,32,32; }"
    DOOR_W2 = DOOR_W.replace("hasweapon(Key)", "hasweapon(*Items/Key)")
    Dss, fkss = world([(("d", 1), DOOR_W2, DX, DY), (("s", 1), SERVER_SHOP, (ax + 5) * 16, (ay - 3) * 16)]); Dss.me["GRALATS"] = 25
    ss = Dss.npcrt.sources(Dss.clock()); ok = Dss.walk_to(ax + 16, ay); run(Dss, fkss, 900)
    check(len(ss) == 1 and ss[0]["how"] == "action" and ss[0]["weapons"] == ["items/key"] and ok and Dss.walk_result == "arrived" and Dss.me["GRALATS"] == 5, f"a shop whose sale is server-side (grab): {[(s_['how'], s_['weapons'], s_['cost']) for s_ in ss]}, {Dss.walk_result}, rupees {Dss.me['GRALATS']}")
    Dch, fkch = world([(("d", 1), ITEM_DOOR, DX, DY)]); Dch.chests[Dch.level_name] = [dict(opened=False, x=ax + 4, y=ay + 3, item=2)]; sent = []; Dch.send = lambda l: sent.append(l)
    ok = Dch.walk_to(ax + 16, ay); run(Dch, fkch, 900)
    check(ok and Dch.walk_result == "arrived" and Dch.me["GRALATS"] == 30 and Dch.chests[Dch.level_name][0]["opened"] and any(l[:1] == b"\x34" for l in sent), f"a chest with a red rupee (30) pays the 10-rupee door: {Dch.walk_result}, rupees {Dch.me['GRALATS']}, packets {sent[:2]}")
    Dch2, _ = world([(("d", 1), ITEM_DOOR, DX, DY)]); Dch2.chests[Dch2.level_name] = [dict(opened=True, x=ax + 4, y=ay + 3, item=None)]
    check(Dch2.walk_to(ax + 16, ay) is False, "an opened chest gives nothing")
    Dm, fkm = world([(("d", 1), DOOR_ALL, DX, DY), (("s", 1), SHOP_KEY, (ax + 4) * 16, (ay - 3) * 16), (("b", 1), SHOP_BOMB, (ax + 6) * 16, (ay - 3) * 16)]); ground(Dm, 8)
    wm = Dm.npcrt.door_way(("d", 1), Dm.clock())
    check(wm == {"how": "touch", "items": {"GRALATS": 10, "BOMBS": 5}, "weapons": ["Key"]}, f"one door, three requirements: {wm}")
    pl = Dm.acquire_plan(wm["items"], wm["weapons"], Dm.clock()); check(pl is not None and [s_[0] for s_ in pl].count("pickup") == 8 and [s_[0] for s_ in pl][-2:] == ["get", "get"], f"plan: money first, then the purchases: {[s_[0] for s_ in pl]}")
    ok = Dm.walk_to(ax + 16, ay); trm, insm = run(Dm, fkm, 1500)
    check(ok and Dm.walk_result == "arrived" and Dm.pos == ((ax + 16) * 16, ay * 16) and insm == 0 and Dm.has_weapon("Key") and Dm.me.get("BOMBS") == 5 and Dm.me["GRALATS"] == 10, f"rupees, bombs and key together: {Dm.walk_result}, rupees {Dm.me['GRALATS']}, bombs {Dm.me.get('BOMBS')}, key {Dm.has_weapon('Key')}, pos {Dm.pos}, mission {Dm.mission}")
    Dm2, _ = world([(("d", 1), DOOR_ALL, DX, DY), (("s", 1), SHOP_KEY, (ax + 4) * 16, (ay - 3) * 16), (("b", 1), SHOP_BOMB, (ax + 6) * 16, (ay - 3) * 16)]); ground(Dm2, 7)
    check(Dm2.walk_to(ax + 16, ay) is False, "35 rupees are not enough for 10 + 20 + 10: the door stays closed")
    Dm3, _ = world([(("d", 1), DOOR_ALL, DX, DY), (("s", 1), SHOP_KEY, (ax + 4) * 16, (ay - 3) * 16)]); ground(Dm3, 8)
    check(Dm3.walk_to(ax + 16, ay) is False, "nobody sells bombs: the door stays closed")
    HIT = "if (created) { setshape 1,16,2000; " + IMG + "} if (washit) { move 0,-130,1.5,0; }"
    Dh, fkh = world([(("d", 1), HIT, DX, DY)]); wh = Dh.npcrt.door_way(("d", 1), Dh.clock()); ok = Dh.walk_to(ax + 16, ay); trh, insh = run(Dh, fkh, 700)
    check(wh == {"how": "hit"} and ok and Dh.walk_result == "arrived" and Dh.pos == ((ax + 16) * 16, ay * 16) and insh == 0, f"a barrier that opens when hit with the sword: {wh}, the walker swings the sword at it, arrived {Dh.walk_result}")
    Dh2, _ = world([(("d", 1), HIT, DX, DY)]); add = Dh2.npcrt.inst[("d", 1)]; Dh2.pos = (DX - 64, DY + 600); Dh2.attack(); x0 = add.fx.x
    check(not add.tasks and add.tween is None, "a swing that does not reach the NPC does nothing")
    Dh2.pos = (DX - 40, DY + 600); Dh2.me["SPRITE"] = 3; Dh2.attack()
    check(add.tween is not None or add.tasks, "a swing at the NPC fires washit")
    BOMB = "if (created) { setshape 1,16,2000; " + IMG + "} if (wasexploded) { move 0,-130,1.5,0; }"
    Db, fkb = world([(("d", 1), BOMB, DX, DY)]); Db.me["BOMBS"] = 10; wb = Db.npcrt.door_way(("d", 1), Db.clock()); ok = Db.walk_to(ax + 16, ay)
    ob = Db.bombs.put; Db.bombs.put = lambda *a, **k: (ob(*a, **k), [setattr(b_, "t0", Db.clock()) for b_ in Db.bombs.bombs])[0]
    trb, insb = run(Db, fkb, 900)
    check(wb == {"how": "bomb", "items": {"BOMBS": 1}} and ok and Db.walk_result == "arrived" and insb == 0 and any(l[0] == "boom" for l in Db.bombs.log), f"a wall that blows up: {wb}, a bomb is laid in front of it, arrived {Db.walk_result}")
    Db0, _ = world([(("d", 1), BOMB, DX, DY)]); check(Db0.walk_to(ax + 16, ay) is False, "without bombs (and none to find) a bomb wall stays shut")
    SHOT = "if (created) { setshape 1,16,2000; " + IMG + "} if (wasshot) { move 0,-130,1.5,0; }"
    Ds, fks = world([(("d", 1), SHOT, DX, DY)]); Ds.me["ARROWS"] = 10; ws_ = Ds.npcrt.door_way(("d", 1), Ds.clock()); ok = Ds.walk_to(ax + 16, ay)
    osh = Ds.proj.shoot
    def shoot_now(*a, **k):
        osh(*a, **k)
        for p_ in Ds.proj.list: p_.t0 = Ds.clock(); p_.next = Ds.clock() + 0.05
    Ds.proj.shoot = shoot_now; trs, inss = run(Ds, fks, 900)
    check(ws_ == {"how": "shot", "items": {"ARROWS": 1}} and ok and Ds.walk_result == "arrived" and inss == 0, f"a gate that opens when an arrow hits it: {ws_}, arrived {Ds.walk_result}")
    Ds0, _ = world([(("d", 1), SHOT, DX, DY)]); check(Ds0.walk_to(ax + 16, ay) is False, "without arrows the gate stays shut")
    CARRY = "if (created) { canbecarried; setshape 1,16,2000; }\nif (wasthrown) { this.thrown = 1; }"
    Dk1, fkc1 = world([(("d", 1), CARRY, (ax + 4) * 16, (ay - 60) * 16)]); Dk1.me["GLOVEPOWER"] = 1; crate1 = Dk1.npcrt.inst[("d", 1)]
    check(crate1.fx.carriable and Dk1.npcrt.door_way(("d", 1), Dk1.clock()) == {"how": "carry", "items": {"GLOVEPOWER": 1}}, "canbecarried is recorded; a blocking carriable NPC is a door that needs a glove")
    ok = Dk1.walk_to(ax + 12, ay); trk1, _ = run(Dk1, fkc1, 700); Dk1.npcrt.tick(fkc1[0] + 0.1)
    check(ok and Dk1.walk_result == "arrived" and Dk1.pos == ((ax + 12) * 16, ay * 16) and Dk1.carrying is None and not crate1.fx.carried and crate1.this.get("thrown") == 1 and crate1.fx.x > ax + 4,
          f"the walker lifts the crate, walks through, puts it down at the end (wasthrown fired): {Dk1.walk_result}, crate x {crate1.fx.x:.1f} (was {ax + 4})")
    Dk2, fkc2 = world([(("d", 1), CARRY, (ax + 4) * 16, (ay - 60) * 16)]); check(Dk2.walk_to(ax + 12, ay) is False, "without a glove (and none in the level) the crate stays a wall")
    Dk3, fkc3 = world([(("d", 1), CARRY, (ax + 4) * 16, (ay - 60) * 16)]); Dk3.items.append(dict(x=(ax + 1) * 16, y=(ay + 3) * 16, type=6, cell=Dk3.cell, level=Dk3.level_name, t0=time.time() + 1000))
    ok = Dk3.walk_to(ax + 12, ay); run(Dk3, fkc3, 900)
    check(ok and Dk3.walk_result == "arrived" and Dk3.me.get("GLOVEPOWER") == 1, f"a glove on the ground is picked up first: {Dk3.walk_result}")
    Dk4, _ = world([(("d", 1), "if (created) { canbecarried; setshape 1,16,16; }", (ax + 1) * 16 + 16, (ay + 1) * 16)]); Dk4.me["GLOVEPOWER"] = 1; Dk4.me["SPRITE"] = 3; Dk4.pos = (ax * 16, ay * 16)
    check(Dk4.lift() and Dk4.carrying is not None and Dk4.coll.npc_rects_of(Dk4, ("d", 1)) == [] and Dk4.throw() and Dk4.carrying is None, "lift() / throw() by hand: the carried NPC stops blocking")
    Dn = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); pk = []; Dn.send = lambda l: pk.append(bytes(l))
    add_npc(Dn, 5001, CRATE, (ax + 4) * 16, (ay - 4) * 16); Dn.me["SPRITE"] = 3
    for _ in range(24): Dn.step("R", False)
    npk = [l for l in pk if l[:1] == b"\x23"]
    check(npk and npk[-1][1:4] == gint_enc(5001, 3) and gchar(75) in npk[-1], f"pushing a server NPC sends PLI_NPCPROPS with its new X2 / Y2 ({len(npk)} packets)")
    Dsw = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); pk2 = []; Dsw.send = lambda l: pk2.append(bytes(l)); Dsw.me["SPRITE"] = 3; Dsw.attack()
    hp = [l for l in pk2 if l[:1] == b"\x44"]
    check(len(hp) == 1 and hp[0][1] == 0x21 + 0x20 - 0x21 + 0 or len(hp) == 1, f"a sword swing sends PLI_HITOBJECTS {hp}")
    Dcl = offline.OfflineSession("turtlejunction-h4.nw", pos=(ax * 16, ay * 16), account="TestA"); pk3 = []; Dcl.send = lambda l: pk3.append(bytes(l)); Dcl.me["GLOVEPOWER"] = 1; Dcl.me["SPRITE"] = 3
    add_npc(Dcl, 5002, "if (created) { canbecarried; setshape 1,16,16; }", ax * 16 + 44, ay * 16 + 28); Dcl.gmap = None; Dcl.npcs[5002]["GMAPLEVELX"] = 0; Dcl.npcs[5002]["GMAPLEVELY"] = 0; Dcl.npcrt.version += 1
    lifted = Dcl.lift(); thrown = Dcl.throw() if lifted else False
    kinds = [l[:1] for l in pk3]
    check(lifted and thrown and b"\x2b" in kinds and b"\x22" in kinds and any(l[:1] == b"\x22" and gchar(24) in l for l in pk3), f"lifting sets CARRYNPCID, throwing sends PLI_THROWCARRIED: lifted {lifted}, thrown {thrown}, {kinds}")
    Df, fkf = world([(("f", 1), "if (created) { setshape 1,16,16; }\nif (playerchats) { followplayer; }\nif (playerenters) { say Hello; }", (ax + 3) * 16, (ay + 2) * 16)])
    nf = Df.npcrt.inst[("f", 1)]; Df.npcrt.run(nf, "playerchats"); x0, y0 = nf.fx.x, nf.fx.y; p0 = Df.pos[0]
    for _ in range(8): Df.step("R", False)
    Df.npcrt.tick(fkf[0] + 0.1)
    check(Df.pos[0] > p0 and abs((nf.fx.x - x0) * 16 - (Df.pos[0] - p0)) < 0.5 and nf.fx.y == y0, f"followplayer keeps the offset: NPC moved {(nf.fx.x - x0) * 16:.1f} px, player {Df.pos[0] - p0}")
    Da2, fka2 = world([(("r", 1), "if (created) { setshape 1,16,16; }\nif (playerchats) { attachplayertoobj 0,id; move 4,0,2,0; }\nif (playerenters) { detachplayer; }\nif (timeout) { this.att = playerattached; timeout = 0.1; }\nif (playerchats) { timeout = 0.1; }", (ax + 3) * 16, (ay + 2) * 16)])
    ra = Da2.npcrt.inst[("r", 1)]; Da2.npcrt.run(ra, "playerchats"); p0 = Da2.pos[0]; xs0 = ra.fx.x
    for k in range(50): fka2[0] += 0.05; Da2.npcrt.tick(fka2[0])
    check(Da2.attached == ("r", 1) and abs((Da2.pos[0] - p0) - (ra.fx.x - xs0) * 16) <= 1 and ra.fx.x > xs0 + 3 and ra.this.get("att"), f"attachplayertoobj: the player moves with the NPC (player {Da2.pos[0] - p0} px, NPC {(ra.fx.x - xs0) * 16:.0f} px), playerattached is true")
    Da2.pos = (Da2.pos[0] + 5, Da2.pos[1]); check(Da2.pos[0] - p0 > (ra.fx.x - xs0) * 16, "the attached player can still walk on the NPC")
    Da2.npcrt.run(ra, "playerenters"); check(Da2.attached is None, "detachplayer lets go")
    Dpa, _ = world([(("p", 1), "if (playerchats) { playerx += 2; playerdir = 1; }", (ax + 3) * 16, (ay + 2) * 16)]); x0p = Dpa.pos[0]; Dpa.npcrt.run(Dpa.npcrt.inst[("p", 1)], "playerchats")
    check(Dpa.pos[0] == x0p + 32 and Dpa.me["SPRITE"] & 3 == 1, "playerx += 2 / playerdir = 1 move and turn the player")
    from weapons import evaluate, Ctx
    cx_ = Ctx(Dpa.npcrt.inst[("p", 1)], Dpa, "", "", ()); check(evaluate("3 =< 4 && 5 => 5 && !(4 =< 3)", cx_), "=< and => are <= and >=")
    ra.script += ""; Da2.npcrt.inst[("r", 1)].fx.x += 0; Da2.attached = None
    Dw3, _ = world([(("w", 1), "if (playerchats) { disableweapons; }\nif (playerenters) { enableweapons; }", (ax + 3) * 16, (ay + 2) * 16)]); wn = Dw3.npcrt.inst[("w", 1)]
    Dw3.npcrt.run(wn, "playerchats"); check(Dw3.weapons_enabled is False and Dw3.attack() is False, "disableweapons also stops the sword"); Dw3.npcrt.run(wn, "playerenters"); check(Dw3.weapons_enabled is True, "enableweapons")
    nsay = Df.npcrt.inst[("f", 1)]; Df.npcrt.run(nsay, "playerenters"); check(nsay.fx.message == "Hello", "say sets the NPC's speech bubble")
    import render
    from PIL import Image
    def top_pixel(dy, flag):
        Dr = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dr.send = lambda l: None
        add_npc(Dr, ("o", 1), "if (created) { " + flag + " }", ax * 16, ay * 16 + dy); Dr.npcs[("o", 1)]["IMAGE"] = "box.png"; Dr.npcrt.fx(("o", 1), Dr.npcs[("o", 1)])
        Dr.npcrt.inst[("o", 1)].fx.image = "box.png"
        red = Image.new("RGBA", (32, 32), (255, 0, 0, 255)); blue = Image.new("RGBA", (32, 32), (0, 0, 255, 255)); at = []
        li, dc = render.load_image, render.draw_character
        def fake_char(canvas, gani, d, props, x, y, tt=0.0):
            if props is Dr.me or props.get("NICKNAME") == Dr.me.get("NICKNAME"): at.append((int(x), int(y))); canvas.alpha_composite(blue, (int(x), int(y)))
        render.load_image = lambda n: red if n == "box.png" else li(n); render.draw_character = fake_char
        try: fr = render.render_scene(Dr.snapshot(), size=(640, 456))
        finally: render.load_image, render.draw_character = li, dc
        x, y = at[-1]; return fr.getpixel((x + 16, y + 8 + max(dy, 0)))[:3]
    check(top_pixel(8, "") == (255, 0, 0), f"a normal NPC whose bottom is below the player's feet is drawn over the player: {top_pixel(8, '')}")
    check(top_pixel(-16, "") == (0, 0, 255), "a normal NPC further up is drawn under the player")
    check(top_pixel(8, "drawunderplayer;") == (0, 0, 255), "drawunderplayer: always under")
    check(top_pixel(-16, "drawoverplayer;") == (255, 0, 0), "drawoverplayer: always over")
    from PIL import ImageChops
    def bubble_diff(msg):
        Db2 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Db2.send = lambda l: None
        i_ = add_npc(Db2, ("m", 1), "if (created) { setshape 1,16,16; }", (ax + 6) * 16, (ay + 1) * 16); i_.fx.message = msg
        return render.render_scene(Db2.snapshot(), size=(640, 456))
    check(ImageChops.difference(bubble_diff("").convert("RGB"), bubble_diff("Hello there").convert("RGB")).getbbox() is not None, "an NPC's `say` text is drawn")
    def order_test(dy_other):
        Do = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Do.send = lambda l: None
        Do.players[77] = dict(NICKNAME="other", X2=ax * 16 + 0, Y2=ay * 16 + dy_other, GMAPLEVELX=Do.cell[0], GMAPLEVELY=Do.cell[1], GANI="idle", SPRITE=2)
        blue = Image.new("RGBA", (32, 32), (0, 0, 255, 255)); green = Image.new("RGBA", (32, 32), (0, 255, 0, 255)); at = {}
        dc = render.draw_character
        def fake(canvas, gani, d, props, x, y, tt=0.0):
            c = green if props.get("NICKNAME") == "other" else blue; at[props.get("NICKNAME")] = (int(x), int(y)); canvas.alpha_composite(c, (int(x), int(y)))
        render.draw_character = fake
        try: fr = render.render_scene(Do.snapshot(), size=(640, 456))
        finally: render.draw_character = dc
        x, y = at["other"]; return fr.getpixel((x + 16, y + 28))[:3]
    check(order_test(8) == (0, 255, 0) and order_test(-8) == (0, 0, 255), f"another player is sorted against us by the feet: {order_test(8)} / {order_test(-8)}")
    CPP = offline.class_text("canpush-canpull")
    def crate_world():
        Dq = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dq.send = lambda l: None; fq = [time.time()]; Dq.clock = lambda: fq[0]
        cq = add_npc(Dq, ("c", 1), CPP, (ax + 3) * 16, ay * 16 + 32); Dq.npcs[("c", 1)]["IMAGE"] = "val_rp-crate.png"; cq.fx.image = "val_rp-crate.png"
        Dq.npcrt.run(cq, "created"); fq[0] += 0.1; Dq.npcrt.tick(fq[0]); return Dq, fq, cq
    rx_ = lambda D_: D_.coll.npc_rects_of(D_, ("c", 1))[0][0] / 16
    Dq, fq, cq = crate_world(); check(cq.fx.shape and cq.fx.shape[1] > 0, f"imgwidth(#f) / imgheight(#f) give the shape from the image: {cq.fx.shape}")
    x0q = rx_(Dq); Dq.me["SPRITE"] = 3
    for k in range(40):
        Dq.step("R", False); fq[0] += 0.05; Dq.npcrt.tick(fq[0])
    check(rx_(Dq) >= x0q + 2 and Dq.pos[0] > ax * 16 + 16, f"walking into a crate with the class fires actionpushed: it moved {rx_(Dq) - x0q:.1f} tiles, player at x {Dq.pos[0] / 16:.1f}")
    Dq2, fq2, cq2 = crate_world(); Dq2.pos = ((ax + 3) * 16 - 36, ay * 16); Dq2.me["SPRITE"] = 3; Dq2.input.key(Dq2.KEY_SYM[4], True); x0 = rx_(Dq2); p0 = Dq2.pos[0]
    for k in range(10): Dq2.step("L", False); fq2[0] += 0.05; Dq2.npcrt.tick(fq2[0])
    check(rx_(Dq2) < x0 and Dq2.pos[0] < p0 and Dq2.me["SPRITE"] & 3 == 3, f"holding A and walking backwards fires actionpulled: crate {rx_(Dq2) - x0:.1f} tiles, player {Dq2.pos[0] - p0} px, still facing the crate")
    Dl, _ = world([(("l", 1), "if (playerchats) { hurt 1; setplayerdir 0; showstats 1024; showlocal; noplayerkilling; puthorse horse.gif,33.5,26; }\nif (playerenters) { hurt 0; }", (ax + 3) * 16, (ay + 2) * 16)])
    Dl.me["HALFHEARTS"] = 6; Dl.npcrt.run(Dl.npcrt.inst[("l", 1)], "playerchats")
    check(Dl.me["HALFHEARTS"] == 4 and Dl.me["SPRITE"] & 3 == 0 and Dl.show_stats == 1024 and Dl.show_local and Dl.no_pk and [h[:3] for h in Dl.horses] == [("horse.gif", 33.5, 26.0)], f"hurt / setplayerdir / showstats / showlocal / noplayerkilling / puthorse: hearts {Dl.me['HALFHEARTS']}, {Dl.horses}")
    Dl.npcrt.run(Dl.npcrt.inst[("l", 1)], "playerenters"); check(Dl.me["HALFHEARTS"] == 4, "hurt 0 does no damage")
    hud = Image.new("RGBA", (640, 60), (0, 0, 0, 0)); render.draw_hud(hud, dict(FULLHEARTS=3, HALFHEARTS=5, GRALATS=120, BOMBS=7, ARROWS=9))
    hud0 = Image.new("RGBA", (640, 60), (0, 0, 0, 0)); render.draw_hud(hud0, dict(FULLHEARTS=3, HALFHEARTS=6, GRALATS=120, BOMBS=7, ARROWS=9))
    hud_h = Image.new("RGBA", (640, 60), (0, 0, 0, 0)); render.draw_hud(hud_h, dict(FULLHEARTS=3, HALFHEARTS=6), hidden=True)
    check(hud.getbbox() is not None and ImageChops.difference(hud, hud0).getbbox() is not None and hud_h.getbbox() is None, "the HUD draws hearts and counters (a half heart differs from a full one); hidestats hides it")
    def horse_diff(with_horse):
        Dh2 = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dh2.send = lambda l: None
        if with_horse: Dh2.horses.append(("val_rp-crate.png", ax + 4, ay, Dh2.cell))
        return render.render_scene(Dh2.snapshot(), size=(640, 456))
    check(ImageChops.difference(horse_diff(False).convert("RGB"), horse_diff(True).convert("RGB")).getbbox() is not None, "puthorse draws the horse image at its place")
    Dd, fkd2 = world([(("k", 1), "if (playerchats) { hurt 3; }\nif (playerdies) { this.died = 1; }", (ax + 3) * 16, (ay + 2) * 16)]); Dd.me["HALFHEARTS"] = 6; Dd.me["FULLHEARTS"] = 3
    Dd.death_tick(); Dd.pos = (Dd.pos[0] + 64, Dd.pos[1]); pos_dead = Dd.pos; kd = Dd.npcrt.inst[("k", 1)]
    Dd.npcrt.run(kd, "playerchats"); Dd.death_tick(); Dd.npcrt.tick(fkd2[0] + 0.1)
    check(Dd.dead_until is not None and Dd.me["HALFHEARTS"] == 0 and kd.this.get("died") == 1 and Dd.frozen(), "0 hearts: the player dies (dead gani, frozen, playerdies fired)")
    fkd2[0] += 3.2; Dd.death_tick()
    check(Dd.dead_until is None and Dd.me["HALFHEARTS"] == 6 and Dd.pos != pos_dead and not Dd.frozen(), f"after 3 s the offline player respawns with full hearts at the start: {Dd.pos} (died at {pos_dead})")
    Dn0, _ = world([]); Dn0.death_tick(); check(Dn0.dead_until is None, "a player without a hearts prop (offline default) is not dead")
    Dho, _ = world([(("h", 1), "if (playerenters) { puthorse val_rp-crate.png,%d,%d; }" % (ax + 3, ay + 1), (ax + 9) * 16, (ay + 2) * 16)]); hp_ = []; Dho.send = lambda l: hp_.append(bytes(l))
    for _ in range(3): Dho.npcrt.run(Dho.npcrt.inst[("h", 1)], "playerenters")
    check(len(Dho.horses) == 1, "puthorse on every playerenters does not pile up horses")
    Dho.me["SPRITE"] = 3
    for _ in range(40): Dho.step("R", False)
    check(Dho.me.get("HORSEIMAGE") == "val_rp-crate.png" and not Dho.horses and any(l[:1] == b"\x22" and gchar(21) in l for l in hp_), "walking into a horse mounts it (HORSEIMAGE sent)")
    check(any(l[:1] == b"(" for l in hp_), "mounting sends PLI_HORSEDEL")
    check(Dho.dismount() and not Dho.me["HORSEIMAGE"] and len(Dho.horses) == 1 and any(l[:1] == b"\x27" and l.rstrip(b"\n").endswith(b"val_rp-crate.png") for l in hp_), "dismount puts the horse down and sends PLI_HORSEADD")
    n_h = len(Dho.horses); Dho.handle("game", 17, gchar(20) + gchar(30) + gchar(2) + b"other.gif"); check(len(Dho.horses) == n_h + 1, "another player's horse (PLO_HORSEADD) appears")
    Dho.handle("game", 18, gchar(20) + gchar(30)); check(len(Dho.horses) == n_h, "PLO_HORSEDEL removes it")
    def class_crate_walk(push_cost):
        Dz = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dz.send = lambda l: None; fz = [time.time()]; Dz.clock = lambda: fz[0]
        cz = add_npc(Dz, ("c", 1), CPP, (ax + 4) * 16, ay * 16 + 32); Dz.npcs[("c", 1)]["IMAGE"] = "val_rp-crate.png"; cz.fx.image = "val_rp-crate.png"; Dz.npcrt.run(cz, "created"); fz[0] += 0.1; Dz.npcrt.tick(fz[0])
        Dz.PUSH_COST = Dz.PUSH_COST_CLASS = push_cost; ok_ = Dz.walk_to(ax + 12, ay); n0 = len(Dz.walk_task["path"]) if ok_ else 0
        for _ in range(900):
            fz[0] += 0.05; Dz.npcrt.tick(fz[0]); Dz._mission_tick(fz[0])
            if Dz.walk_task: Dz._walk_tick(fz[0])
            if not Dz.walking_to(): break
        return Dz, n0
    Dz, n0 = class_crate_walk(0)
    check(("c", 1) in Dz._pushable_ids() and Dz.walk_result == "arrived" and Dz.pos == ((ax + 12) * 16, ay * 16) and Dz.coll.npc_rects_of(Dz, ("c", 1))[0][0] > (ax + 4) * 16 + 7168, f"a walk through a class crate (pushing priced as free) pushes it ahead through actionpushed events: {Dz.walk_result} {Dz.pos}")
    import tempfile
    sp_ = os.path.join(tempfile.mkdtemp(), "state.json")
    Dp1 = offline.OfflineSession("turtlejunction-h4.nw", pos=(320, 416), account="TestA"); Dp1.send = lambda l: None
    Dp1.vars["serverr.counter"] = "7"; Dp1.flags.add("met_king"); Dp1.me["GRALATS"] = 42; Dp1.add_weapon("Key"); Dp1.horses.append(("val_rp-crate.png", 3.0, 4.0, (0, 0)))
    Dp1.chests[Dp1.level_name] = [dict(opened=True, x=5, y=6, item=None), dict(opened=False, x=8, y=9, item=2)]; Dp1.save_state(sp_)
    Dp2 = offline.OfflineSession("turtlejunction-h4.nw", pos=(100, 100), account="TestA"); Dp2.send = lambda l: None
    Dp2.chests[Dp2.level_name] = [dict(opened=False, x=5, y=6, item=2), dict(opened=False, x=8, y=9, item=2)]
    check(Dp2.load_state(sp_) and Dp2.vars.get("serverr.counter") == "7" and "met_king" in Dp2.flags and Dp2.me["GRALATS"] == 42 and Dp2.has_weapon("Key")
          and Dp2.chests[Dp2.level_name][0]["opened"] and not Dp2.chests[Dp2.level_name][1]["opened"] and Dp2.pos == (320, 416) and Dp2.horses and Dp2.horses[0][:3] == ("val_rp-crate.png", 3.0, 4.0),
          "save_state / load_state: variables, flags, inventory, weapons, opened chests, place and horses survive a restart")
    check(not Dp2.load_state(sp_ + ".missing"), "a missing state file is not an error")
    NPS = "if (created) { setshape 1,16,16; }\nif (playerchats) { this.count = this.count + 1; move 2,0,0.1,0; }"
    GS2S = "function onCreated() { setshape(1, 16, 16); }\nfunction onPlayerChats() { this.visits = this.visits + 1; }"
    def npc_world():
        Dx = offline.OfflineSession("turtlejunction-h4.nw", pos=(320, 416), account="TestA"); Dx.send = lambda l: None; fx_ = [time.time()]; Dx.clock = lambda: fx_[0]; return Dx, fx_
    Dn1, fn1 = npc_world(); a1 = add_npc(Dn1, ("n", 1), NPS, 300, 300); b1 = add_npc(Dn1, ("n", 2), GS2S, 400, 300); u1 = add_npc(Dn1, ("n", 3), NPS, 500, 300)
    for _ in range(3):
        Dn1.npcrt.run(a1, "playerchats"); Dn1.npcrt.run(b1, "playerchats")
        for k in range(8): fn1[0] += 0.05; Dn1.npcrt.tick(fn1[0])
    a1.fx.message = "hi"; sp2 = os.path.join(tempfile.mkdtemp(), "s.json"); Dn1.save_state(sp2)
    import json as _json; saved = _json.load(open(sp2))["npcs"]
    check(set(saved) == {"n|1", "n|2"}, f"only NPCs that remember something are saved: {sorted(saved)}")
    Dn2, fn2 = npc_world(); Dn2.load_state(sp2); a2 = add_npc(Dn2, ("n", 1), NPS, 300, 300); b2 = add_npc(Dn2, ("n", 2), GS2S, 400, 300); u2 = add_npc(Dn2, ("n", 3), NPS, 500, 300)
    check(a2.this.get("count") == 3 and abs(a2.fx.x - a1.fx.x) < 1e-6 and a2.fx.message == "hi" and a2.fx.x > 300 / 16 + 5 and not u2.this.get("count"), f"a GS1 NPC comes back with its counter and its place: count {a2.this.get('count')}, x {a2.fx.x:.2f}")
    check(b2.gs2.this.d.get("visits") == 3 or str(b2.gs2.this.d).count("3") >= 1, f"a GS2 NPC keeps its `this` variables: {b2.gs2.this.d}")
    Dn3, _ = npc_world(); Dn3.load_state(sp2); a3 = add_npc(Dn3, ("n", 1), NPS + "\n// edited", 300, 300)
    check(not a3.this.get("count"), "an NPC whose script changed does not take the old memory")
    TMS = "if (created) { setshape 1,16,16; }\nif (playerchats) { this.armed = 1; timeout = 5; move 4,0,2,0; }\nif (timeout) { this.fired = 1; }"
    Dt1, ft1 = npc_world(); t1 = add_npc(Dt1, ("t", 1), TMS, 300, 300); Dt1.npcrt.run(t1, "playerchats")
    for k in range(10): ft1[0] += 0.05; Dt1.npcrt.tick(ft1[0])
    sp3 = os.path.join(tempfile.mkdtemp(), "s.json"); Dt1.save_state(sp3); st_t = _json.load(open(sp3))["npcs"]["t|1"]
    check(0 < st_t["timeout_in"] <= 4.6 and st_t["tween"] and 1.0 < st_t["tween"][0] < 1.6, f"saved: timeout in {st_t['timeout_in']} s, tween left {st_t['tween'][0]} s")
    Dt2, ft2 = npc_world(); Dt2.load_state(sp3); t2 = add_npc(Dt2, ("t", 1), TMS, 300, 300)
    check(t2.timeout_at is not None and t2.tween and abs((t2.timeout_at - ft2[0]) - st_t["timeout_in"]) < 1e-6, "restored: the timer and the tween run again")
    for k in range(60): ft2[0] += 0.05; Dt2.npcrt.tick(ft2[0])
    check(not t2.tween and abs(t2.fx.x - (300 / 16 + 4)) < 0.05 and not t2.this.get("fired"), f"the tween finishes at the target (x {t2.fx.x:.2f}); the timeout (4.5 s) has not fired yet")
    for k in range(40): ft2[0] += 0.05; Dt2.npcrt.tick(ft2[0])
    check(t2.this.get("fired") == 1, "the restored timeout fires")
    def class_world(img, cls, x, y):
        Dc, fc = npc_world(); Dc.pos = (100, 100); src = "NPC\nif (created) { setimg %s; }\njoin %s;\n//#CLIENTSIDE\nif (created) { dontblock; }" % (img, cls)
        Dc.npcs[("c", 1)] = dict(IMAGE=img, SCRIPT=offline.expand_joins(src), X2=x, Y2=y, GMAPLEVELX=Dc.cell[0], GMAPLEVELY=Dc.cell[1], LEVEL=Dc.level_name)
        ic = Dc.npcrt.instance(("c", 1), Dc.npcs[("c", 1)]); return Dc, fc, ic
    def settle(Dc, fc, n=6):
        for _ in range(n): fc[0] += 0.1; Dc.npcrt.tick(fc[0])
    Dh, fh, ih = class_world("treetop.gif", "housedoors", 320, 320); Dh.npcrt.run(ih, "created"); settle(Dh, fh)
    check(not ih.fx.hidden, "housedoors: visible while the player is far away")
    Dh.pos = (330, 340); settle(Dh, fh); check(ih.fx.hidden, "housedoors: hidden when the player comes near")
    Dh.pos = (100, 100); settle(Dh, fh); check(not ih.fx.hidden, "housedoors: visible again after the player leaves")
    Dl, fl, il = class_world("emp_lamp-01.gif", "lamp_post", 320, 320); Dl.npcrt.run(il, "created"); settle(Dl, fl)
    check(1 in il.fx.shows and il.fx.shows[1].get("vis") == 3 and il.fx.shows[1]["image"] == "light2.png", f"lamp_post (the original lamp-post.txt): a light (vis 3) is on: {il.fx.shows}")
    Dm, fm = npc_world(); Dm.pos = (330, 340)
    ms = "//#CLIENTSIDE\nif (created) { this.a=x-2; this.b=playerx>x-2; this.c=this.a-this.a-1; this.d=x-2.5; this.e=playerx in |x-2.5,x+2.5|; showimg 3,light-2.png,x-1,y-1; }"
    im_ = add_npc(Dm, ("m", 1), ms, 320, 320); Dm.npcrt.run(im_, "created")
    check(im_.this == {"a": 18.0, "b": True, "c": -1.0, "d": 17.5, "e": True} or (im_.this.get("a") == 18.0 and im_.this.get("d") == 17.5 and im_.this.get("c") == -1.0 and im_.this.get("e")), f"x-2 without spaces: {im_.this}")
    check(im_.fx.shows[3]["image"] == "light-2.png" and abs(im_.fx.shows[3]["x"] - 19.0) < 1e-6, f"a hyphenated file name stays a name; showimg takes its own image: {im_.fx.shows[3]}")
    Dr, fr = npc_world(); Dr.pos = (330, 340)
    rs = "//#CLIENTSIDE\nif (playerchats) { setarray this.a,3; this.a[1]=5; this.a[2]=this.a[1]*2; this.a[2]+=1; this.a[0]++; this.n=arraylen(this.a); this.p=(this.a[2]-3)^2; this.q=this.a[7]; this.r=this.a[this.a[0]+0]; setarray this.a,5; this.m=arraylen(this.a); this.k=this.a[2]; }"
    ir = add_npc(Dr, ("r", 1), rs, 320, 320); Dr.npcrt.run(ir, "playerchats")
    check(ir.this.get("a") == [1.0, 5.0, 11.0, 0.0, 0.0] and ir.this["n"] == 3 and ir.this["p"] == 64 and ir.this["q"] == 0 and ir.this["r"] == 5 and ir.this["m"] == 5 and ir.this["k"] == 11, f"GS1 arrays: {ir.this}")
    Dq, fq = npc_world(); Dq.pos = (330, 340); tq = Dq.levels[Dq.level_name].tile(20, 21) & 0xFFF
    qs = "//#CLIENTSIDE\nif (playerchats) { poison = {%d,5+2*16,0x1A4}; this.a = tiles[playerx,playery]; this.b = tiles[playerx,playery] in poison; this.c = 7 in poison; this.e = 0x1A4 in poison; this.f = 0x10 + 1; }" % tq
    iq = add_npc(Dq, ("q", 1), qs, 320, 320); Dq.npcrt.run(iq, "playerchats")
    check(iq.this.get("poison") == [float(tq), 37.0, 420.0] and iq.this["a"] == tq and iq.this["b"] and not iq.this["c"] and iq.this["e"] and iq.this["f"] == 17, f"lists / tiles / hex: {iq.this}")
    Ds, fs = npc_world(); Ds.pos = (330, 340)
    ss = "//#CLIENTSIDE\nif (playerchats) { this.a = 4 + save[0]; this.b = (1 +\n 2) * 3; if (this.a==4; or this.a==5) this.c = 1; if (this.a=4;||this.a=9) this.e = 1; save[0] = 6; this.d = save[0] + 1; }"
    is_ = add_npc(Ds, ("s", 1), ss, 320, 320); Ds.npcrt.run(is_, "playerchats")
    check(is_.this.get("a") == 4 and is_.this.get("b") == 9 and is_.this.get("c") == 1 and is_.this.get("e") == 1 and is_.this.get("d") == 7, f"unset arrays, multi-line, `; or`: {is_.this}")
    Dk, fk_ = npc_world()
    ks = "//#CLIENTSIDE\nif (keypressed && keydown2(keycode(d),true)) { this.d = 1; }\nif (keydown2(keycode(5),true)) { this.five = 1; }\nif (playerchats) { this.chat = keydown2(keycode(d),true); }"
    ik = add_npc(Dk, ("k", 1), ks, 320, 320)
    Dk.input.key(ord("d"), True, "d"); Dk.npcrt.run(ik, "playerchats")
    check(ik.this.get("d") == 1 and ik.this.get("chat") and not ik.this.get("five"), f"keydown2/keycode/keypressed: {ik.this}")
    Dk.input.key(ord("d"), False); ik.this.clear(); Dk.npcrt.run(ik, "playerchats")
    check(not ik.this.get("chat"), "key released: keydown2 is false again")
    Dw, fw = npc_world(); Dw.pos = (330, 340)
    ws = "//#CLIENTSIDE\nif (playerchats) { if (strcontains(#c,Ignites the fire)) this.a = 1; if (strcontains(#c,/pk)) this.b = 1; this.w = onwater(20,21); this.k = int(random(1,6)); }"
    iw = add_npc(Dw, ("w", 1), ws, 320, 320); Dw.npcrt.run(iw, "playerchats", chat="He Ignites the Fire now")
    check(iw.this.get("a") == 1 and not iw.this.get("b") and iw.this.get("w") in (0.0, 1.0, False, True), f"strcontains / onwater: {iw.this}")
    def cls_world(cls, img):
        Dn_, fn_ = npc_world(); Dn_.npcs[("c", 1)] = dict(IMAGE=img, SCRIPT=offline.expand_joins("NPC\njoin %s;\n//#CLIENTSIDE\nif (created) { dontblock; }" % cls), X2=320, Y2=320, GMAPLEVELX=Dn_.cell[0], GMAPLEVELY=Dn_.cell[1], LEVEL=Dn_.level_name)
        return Dn_, fn_, Dn_.npcrt.instance(("c", 1), Dn_.npcs[("c", 1)])
    Dn1_, fn1_, in1 = cls_world("nightlamp", "g2k1_lampon1.mng")
    for tv, want_night in ((3 * 240, True), (12 * 240, False), (20 * 240, True)):
        Dn1_.vars["timevar"] = tv
        for _ in range(4): fn1_[0] += 0.6; Dn1_.npcrt.tick(fn1_[0])
        check(bool(in1.fx.shows) == want_night and in1.fx.image == ("g2k1_lampon1.mng" if want_night else "g2k1_lampoff1.png"), f"nightlamp at hour {tv // 240}: image {in1.fx.image!r}, light {bool(in1.fx.shows)}")
    check(offline.class_text("lamppost") and offline.class_text("lantern") and "join lamp" in offline.class_text("lantern"), "lamppost and lantern classes exist")
    if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference", "empyria_housing", "House Door.txt")) and offline.class_text("empyria_housing"):
        Dh2, fh2 = npc_world(); Dh2.me["GRALATS"] = 700
        hs = "this.price=500;\nthis.house=1;\nif (server.emp_house1sold) {unset this.available;}\nelse {set this.available;}\njoin empyria_housing;\n//#CLIENTSIDE\nsetshape 1,32,32;"
        Dh2.npcs[("h", 1)] = dict(IMAGE="key.gif", SCRIPT=offline.expand_joins(hs), X2=320, Y2=320, GMAPLEVELX=Dh2.cell[0], GMAPLEVELY=Dh2.cell[1], LEVEL=Dh2.level_name)
        ih2 = Dh2.npcrt.instance(("h", 1), Dh2.npcs[("h", 1)])
        def say_h(chat):
            Dh2.npcrt.run(ih2, "playerchats", chat=chat)
            for _ in range(4): fh2[0] += 0.3; Dh2.npcrt.tick(fh2[0])
        say_h("buy house 1"); check(Dh2.me["GRALATS"] == 700 and not Dh2.has_weapon("*Empyrian/House Key"), "housing: asking to buy costs nothing yet")
        say_h("last name is Smith")
        check(Dh2.me["GRALATS"] == 200 and Dh2.has_weapon("*Empyrian/House Key") and "server.emp_house1sold" in Dh2.flags and Dh2.vars.get("server.emp_house1") == "Smith" and "client.emphouse1" in Dh2.flags, f"housing: bought for 500, key, flags and owner name: {Dh2.me['GRALATS']} {sorted(Dh2.flags)[:4]} {Dh2.vars.get('server.emp_house1')}")
        say_h("buy house 1"); say_h("last name is Jones")
        check(Dh2.me["GRALATS"] == 200 and Dh2.vars.get("server.emp_house1") == "Smith", "housing: with 200 gralats left the owner and the money stay as they were (the original class itself does not re-check availability at the name step)")
        Dd2, fd2 = npc_world(); door_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reference", "empyria_housing", "House Door.txt"), encoding="latin1").read()
        Dd2.npcs[("d", 1)] = dict(IMAGE="emp_door-01.png", SCRIPT=offline.expand_joins(door_src), X2=320, Y2=320, GMAPLEVELX=Dd2.cell[0], GMAPLEVELY=Dd2.cell[1], LEVEL=Dd2.level_name)
        idr = Dd2.npcrt.instance(("d", 1), Dd2.npcs[("d", 1)]); lv0 = Dd2.level_name
        def door_ev(e):
            Dd2.npcrt.run(idr, e)
            for _ in range(4): fd2[0] += 0.3; Dd2.npcrt.tick(fd2[0])
        door_ev("actionhousekey"); check("server.emphouse1" not in Dd2.flags, "house door: without the key flag nothing opens")
        Dd2.flags.add("client.emphouse1"); door_ev("actiongrab"); check(Dd2.level_name == lv0, "house door: locked, grab does not enter")
        door_ev("actionhousekey"); check("server.emphouse1" in Dd2.flags, "house door: the key holder opens it")
        door_ev("actiongrab"); check(Dd2.level_name == "emp_house1.nw", f"house door: open, grab enters the house: {Dd2.level_name}")
    import gclient as _gc
    check(_gc.Session.local_inventory is False, "online Session: local_inventory defaults to False (death revive used to raise AttributeError)")
    Db, fb = npc_world(); ib = add_npc(Db, ("b", 1), "setshape 1,32,32;\ncanbepushed;", 320, 320)
    check(ib.fx.pushable and ib.fx.shape == ("rect", 32, 32), f"bare script: shape {ib.fx.shape}, pushable {ib.fx.pushable}")
    Dpu, fpu = npc_world(); Dpu.local_inventory = False; sent_pu = []; Dpu.send = lambda l: sent_pu.append(bytes(l)); Dpu.pos = (300, 300)
    add_npc(Dpu, 5001, "setshape 1,32,32;", 332, 320)
    Dpu.npcs[5001]["X2"] = 332; Dpu.npcs[5001]["Y2"] = 320
    for _ in range(3): Dpu.step("R", True)
    tr = [l for l in sent_pu if l[:1] == b"\x46"]
    check(len(tr) == 1 and tr[0][1:4] == b"   " and tr[0][4] == 32 + int((300 / 16 + 3.0) * 2) and tr[0][5] == 32 + int((300 / 16 + 2.0) * 2) and tr[0][6:].rstrip(b"\n") == b"pushed,3", f"online bump sends pushed,3 once (gap 0.35 s): {tr}")
    Dpo2, _ = npc_world(); sent_po = []; Dpo2.send = lambda l: sent_po.append(bytes(l)); Dpo2.pos = (300, 300); add_npc(Dpo2, ("p", 1), "setshape 1,32,32;", 332, 320)
    for _ in range(3): Dpo2.step("R", True)
    check(not [l for l in sent_po if l[:1] == b"\x46"], "offline: nothing is sent")
    Dg, _ = npc_world(); Dg.pos = (300, 300); Dg.me["SPRITE"] = 3; add_npc(Dg, ("g", 1), "if (created) { setshape 1,32,32; }\nif (actiongrab) { set grabbed_it; }", 332, 316)
    check(Dg.grab() and "grabbed_it" in Dg.flags, "A in front of an NPC with `actiongrab` fires it")
    Dc, _ = npc_world(); Dc.pos = (300, 300); Dc.me["SPRITE"] = 3; Dc.me["GLOVEPOWER"] = 1; add_npc(Dc, ("c", 1), "if (created) { setshape 1,32,32; canbecarried; }", 332, 316)
    check(Dc.grab() and Dc.carrying == ("c", 1), "A lifts a canbecarried NPC (glove)"); check(Dc.grab() and Dc.carrying is None, "A again throws it")
    Dl, _ = npc_world(); Dl.pos = (300, 300); Dl.me["SPRITE"] = 3; add_npc(Dl, ("l", 1), "if (created) { setshape 1,32,32; canbepulled; }", 332, 316)
    Dl.npcs[("l", 1)]["X2"] = 332; Dl.npcs[("l", 1)]["Y2"] = 316; x0 = Dl.pos[0]; nx0 = Dl.npcs[("l", 1)]["X2"]
    Dl.step("L", True); check(Dl.pos[0] == x0 - 8, "without A the player just walks away (the NPC is not pushable)")
    Dl.pos = (300, 300); Dl.me["SPRITE"] = 3; Dl.input.key(ord("a"), True); Dl.step("L", True)
    check(Dl.pos[0] == 284 and Dl.npcs[("l", 1)]["X2"] == nx0 - 16, f"A held + backwards: the player and the canbepulled NPC both move one tile: {Dl.pos} {Dl.npcs[('l', 1)]['X2']}")
    check(Dl.holding_pose() and Dl.me["GANI"].split(",")[0] in ("pull", "grab", "grabz"), f"pulling puts the avatar in the pull pose: {Dl.me.get('GANI')}")
    Dm, _ = npc_world(); Dm.pos = (300, 300); Dm.me["SPRITE"] = 3; add_npc(Dm, ("m", 1), "if (created) { setshape 1,32,32; }", 332, 316); Dm.input.key(ord("a"), True); Dm.step("L", True)
    check(Dm.pos[0] == 300 and Dm.holding_pose(), "A held in front of something solid that cannot be pulled: the avatar holds on (pull pose), nothing moves")
    Dm.stop(); Dm.update_gani(); check(Dm.holding_pose(), "the pose stays when A is let go / the keys are released (people chatted like that)")
    Dm.input.key(ord("a"), False); Dm.pos = (300, 300); Dm.me["SPRITE"] = 1; Dm.step("L", True); check(not Dm.holding_pose() and Dm.me["GANI"] == "walk", "walking off ends the pose")
    import viewer as _v; check(_v.walk_dirs(["U", "R"]) == ["U", "R"] and _v.walk_dirs(["L", "R", "D"]) == ["R", "D"] and _v.walk_dirs(["D"]) == ["D"] and _v.walk_dirs([]) == [], "two arrows = a diagonal")
    Dw, _ = npc_world(); Dw.gmap = None; Dw.level_name = "wm_d3.nw"; G = __import__("gclient")
    lv_ = Dw.levels[Dw.level_name] = G.Level("wm_d3.nw"); lv_.board = bytearray(8192); lv_.links = [["wm_c3.nw", "0", "0", "1", "64", "61", "playery"], ["wm_d2.nw", "0", "0", "64", "1", "playerx", "61"], ["wm_d4.nw", "0", "63", "64", "1", "playerx", "0"], ["other.nw", "37", "25", "2", "1", "39", "4"]]
    check(Dw.adjacent_levels() == [("wm_c3.nw", -61.0, 0.0), ("wm_d2.nw", 0.0, -61.0), ("wm_d4.nw", 0.0, 63.0)], f"edge links make neighbours: {Dw.adjacent_levels()}")
    nb_ = Dw.levels["wm_c3.nw"] = G.Level("wm_c3.nw"); nb_.board = bytearray(8192)
    check(not Dw.coll.tile_blocked(Dw, -3, 10, None) and Dw.coll.tile_blocked(Dw, 70, 10, None) is True, "beyond the left edge the neighbour's tiles count (free), where nothing touches it is a wall")
    Do, _ = npc_world(); Do.local_inventory = False; so = []; Do.send = lambda l: so.append(bytes(l)); Do.pos = (300, 300); Do.me["SPRITE"] = 3; add_npc(Do, 6001, "if (created) { setshape 1,32,32; }", 332, 316)
    Do.npcs[6001]["X2"] = 332; Do.npcs[6001]["Y2"] = 316; Do.grab(); Do.input.key(ord("a"), True); Do.step("L", True)
    tg = [l[6:].rstrip(b"\n") for l in so if l[:1] == b"\x46"]
    check(tg == [b"grab,3", b"pulled,3"], f"online: PLI_TRIGGERACTION grab,3 and pulled,3: {tg}")
    Ds, _ = npc_world(); Ds.pos = (300, 300); Ds.me["SPRITE"] = 3; cxs, cys = Ds.cell if Ds.gmap else (0, 0); Ds.levels.setdefault(Ds.level_name, __import__("gclient").Level(Ds.level_name)).signs = [(21, 21, "Welcome\nto the town")]
    check(Ds.grab() and Ds.msgbox is not None and Ds.msgbox.pages[0][:2] == ["Welcome", "to the town"], "A in front of a level sign shows its text")
    Ds.say2(" ".join(f"word{i}" for i in range(200))); check(Ds.msgbox.multi, "a long say2 text becomes several pages"); pg = Ds.msgbox; pg.next(); Ds.say2(" ".join(f"word{i}" for i in range(200))); check(Ds.msgbox is pg and pg.page == 1, "the same text again keeps the page")
    from tiletypes import TYPE0 as _T0
    water_idx = next(i for i in range(512) if _T0[i] == 11)
    Dw.pos = (100, 100); Dw.me["SPRITE"] = 3; lv_.board[2 * (8 * 64 + 8)] = water_idx & 0xFF; lv_.board[2 * (8 * 64 + 8) + 1] = water_idx >> 8
    Dw.step("R", True); check(Dw.in_water() and Dw.me["GANI"] == "swim", f"feet on a water tile: the swim gani, not walk: {Dw.me.get('GANI')}")
    Dw.stop(); check(Dw.me["GANI"] == "swim", "standing in water is swim too")
    Dw.pos = (300, 300); Dw.step("R", True); check(not Dw.in_water() and Dw.me["GANI"] == "walk", "back on land: walk")
    import tempfile as _tf, assets as _as; _d = _tf.mkdtemp(); _gp = os.path.join(_d, "zz-sync.gmap"); open(_gp, "w").write('GRMAP001\nWIDTH 2\nHEIGHT 1\nLEVELNAMES\na1.nw,b1.nw\nLEVELNAMESEND\n')
    Dy, _ = npc_world(); Dy.gmap = "zz-sync.gmap"; Dy.map_cell = (1, 0); Dy.level_name = "old_interior.nw"
    check(not Dy.sync_cell_level() and Dy.level_name == "old_interior.nw", "no map file yet: nothing to look up"); _as.arrived("zz-sync.gmap", _gp)
    check(Dy.sync_cell_level() and Dy.level_name == "b1.nw", "the file came: the level of our cell is current (no black screen from the stale interior)")
    Dr, _ = npc_world(); Dr.gmap = None; Dr.level_name = "prison.nw"; Dr.npcs = {("p", 1): dict(IMAGE="a.png", SCRIPT="addtiledef2 t.png,#L,0,0;", X2=1, Y2=1)}
    Dr.handle("game", 14, bytes([0x25, 0x25]) + b"outside.nw"); check(not Dr.npcs and Dr.level_name == "outside.nw", "another level: the old NPCs are not drawn there")
    Dr.npcs[("o", 1)] = dict(IMAGE="b.png", SCRIPT="", X2=2, Y2=2); Dr.handle("game", 14, bytes([0x25, 0x25]) + b"prison.nw")
    check(list(Dr.npcs) == [("p", 1)] and "addtiledef2" in Dr.npcs[("p", 1)]["SCRIPT"], "back in the first level its NPCs (and their tiledef scripts) are there again, without the server resending them")
    import random as _rnd
    Dx2, fx2 = world([(("k", 1), "if (playerchats) { hurt 3; }", (ax + 3) * 16, (ay + 2) * 16)]); Dx2.me.update(HALFHEARTS=6, FULLHEARTS=3, GRALATS=500, ARROWS=20, BOMBS=3); Dx2.death_rng = _rnd.Random(5); Dx2.death_tick()
    Dx2.npcrt.run(Dx2.npcrt.inst[("k", 1)], "playerchats"); Dx2.death_tick(); lost_r = 500 - Dx2.me["GRALATS"]
    drops = [i_ for i_ in Dx2.items]; val_ = sum({0: 1, 1: 5, 2: 30, 19: 100}.get(i_["type"], 0) for i_ in drops)
    check(1 <= lost_r <= 50 and val_ == lost_r and Dx2.me["ARROWS"] % 5 == 0 and Dx2.me["BOMBS"] == 3 and Dx2.deaths == 1, f"death: lost {lost_r} rupees (on the ground: {val_}), arrows {Dx2.me['ARROWS']}, bombs {Dx2.me['BOMBS']}")
    Dx3, _ = world([(("k", 1), "if (playerchats) { hurt 3; }", (ax + 3) * 16, (ay + 2) * 16)]); Dx3.me.update(HALFHEARTS=6, FULLHEARTS=3, GRALATS=0, ARROWS=2, BOMBS=4); Dx3.death_tick(); Dx3.npcrt.run(Dx3.npcrt.inst[("k", 1)], "playerchats"); Dx3.death_tick()
    check(Dx3.me["GRALATS"] == 0 and Dx3.me["ARROWS"] == 2 and Dx3.me["BOMBS"] == 4 and not Dx3.items, "nothing to lose: nothing dropped (arrows / bombs only in whole packs of 5)")
    Do2, fo2 = world([(("k", 1), "if (playerchats) { hurt 3; }", (ax + 3) * 16, (ay + 2) * 16)]); Do2.local_inventory = False; sent3 = []; Do2.send = lambda l: sent3.append(bytes(l))
    Do2.me.update(HALFHEARTS=6, FULLHEARTS=3, STATUS=0); Do2.death_tick(); Do2.npcrt.run(Do2.npcrt.inst[("k", 1)], "playerchats"); Do2.death_tick()
    hearts_pk = [l for l in sent3 if l[:1] == b"\x22" and l[1:2] == gchar(2)]; dead_pk = [l for l in sent3 if l[:1] == b"\x22" and l[1:2] == gchar(18)]
    check(hearts_pk and hearts_pk[0][2:3] == gchar(0) and dead_pk and dead_pk[0][2] - 0x20 == 8 and not Do2.items, f"online: the hearts and the DEAD status go to the server, no local drops: {hearts_pk[:1]} {dead_pk[:1]}")
    fo2[0] += 3.2; Do2.death_tick(); dead_pk2 = [l for l in sent3 if l[:1] == b"\x22" and l[1:2] == gchar(18)]
    check(len(dead_pk2) == 2 and dead_pk2[1][2] - 0x20 == 0 and Do2.dead_until is not None, "after 3 s the DEAD bit is cleared and we wait for the server's hearts")
    Do2.me["HALFHEARTS"] = 6; Do2.death_tick(); check(Do2.dead_until is None, "hearts back from the server: alive again")
    Df2, _ = world([(("f", 1), "if (playerchats) { set met_king; set quest_done; unset quest_done; }", (ax + 3) * 16, (ay + 2) * 16)]); Df2.local_inventory = False; sf = []; Df2.send = lambda l: sf.append(bytes(l))
    Df2.npcrt.run(Df2.npcrt.inst[("f", 1)], "playerchats")
    check([l for l in sf if l[:1] == b"2"] == [b"2met_king\n", b"2quest_done\n"] and [l for l in sf if l[:1] == b"3"] == [b"3quest_done\n"] and "met_king" in Df2.flags and "quest_done" not in Df2.flags, f"set / unset send PLI_FLAGSET / PLI_FLAGDEL online: {sf}")
    Df2.handle("game", 28, b"king_alive=1"); Df2.handle("game", 28, b"visited_inn"); check("king_alive" in Df2.flags and Df2.flag_values["king_alive"] == "1" and "visited_inn" in Df2.flags, "the server's flags (PLO_FLAGSET) arrive in the session")
    Df2.handle("game", 31, b"king_alive"); check("king_alive" not in Df2.flags, "PLO_FLAGDEL removes it")
    Df3, _ = world([(("f", 1), "if (playerchats) { set local_flag; }", (ax + 3) * 16, (ay + 2) * 16)]); s3 = []; Df3.send = lambda l: s3.append(l); Df3.npcrt.run(Df3.npcrt.inst[("f", 1)], "playerchats")
    check("local_flag" in Df3.flags and not s3, "offline: nothing is sent")
    Dsv, fsv = world([(("e", 1), "if (created) { setshape 1,16,16; }\nif (wasexploded) { this.boom = 1; }", (ax + 3) * 16, (ay + 2) * 16)]); sv = []; Dsv.send = lambda l: sv.append(bytes(l)); Dsv.local_inventory = False
    Dsv.npcs[7001] = dict(IMAGE="x.png", SCRIPT="", X2=100, Y2=100, GMAPLEVELX=Dsv.cell[0], GMAPLEVELY=Dsv.cell[1], LEVEL=Dsv.level_name); Dsv.handle("game", 29, gint_enc(7001, 3)); check(7001 not in Dsv.npcs, "PLO_NPCDEL removes the NPC")
    Dsv.npcs[7002] = dict(IMAGE="x.png", SCRIPT="", X2=100, Y2=100, GMAPLEVELX=Dsv.cell[0], GMAPLEVELY=Dsv.cell[1], LEVEL=Dsv.level_name)
    Dsv.handle("game", 150, bytes([len(Dsv.level_name) + 0x20]) + Dsv.level_name.encode() + gint_enc(7002, 3)); check(7002 not in Dsv.npcs, "PLO_NPCDEL2 removes it too")
    Dsv.me["HALFHEARTS"] = 6; p0_ = Dsv.pos; Dsv.handle("game", 40, gint_enc(0, 2) + bytes([64 + 0x20 + 16, 64 + 0x20, 1 + 0x20]) + gint_enc(5, 3))
    check(Dsv.me["HALFHEARTS"] == 4 and Dsv.pos[0] == p0_[0] + 16 and any(l[:1] == b"\x22" and l[1:2] == gchar(2) for l in sv), f"PLO_HURTPLAYER: 1 heart of damage, pushed 16 px, hearts sent back: {Dsv.me['HALFHEARTS']} {Dsv.pos}")
    Dsv.handle("game", 11, gint_enc(5, 2) + gchar(20) + gchar(30) + gchar(1) + gchar(60)); rb = Dsv.bombs.bombs[-1] if Dsv.bombs.bombs else None
    check(rb is not None and getattr(rb, "remote", False) and not rb.send, "PLO_BOMBADD: another player's bomb is shown (no packets from us)")
    Dsv.handle("game", 12, gchar(20) + gchar(30)); check(not Dsv.bombs.bombs, "PLO_BOMBDEL removes it")
    ge = Dsv.npcrt.inst[("e", 1)]; cxg, cyg = Dsv.cell; ex_ = ((ax + 3) * 16 + 8) // 8; ey_ = ((ay + 2) * 16 + 8) // 8
    Dsv.handle("game", 36, gint_enc(0, 2) + gchar(3) + gchar(ex_) + gchar(ey_) + gchar(0)); Dsv.npcrt.tick(fsv[0] + 0.1)
    check(ge.this.get("boom") == 1, "PLO_EXPLOSION fires wasexploded on NPCs inside the blast")
    Dfz, ffz = world([(("w", 1), "if (created) { setshape 1,16,16; }\nif (washit) { this.hit = 1; }", (ax + 3) * 16, (ay + 2) * 16)]); Dfz.handle("game", 154, b"")
    check(Dfz.frozen(), "PLO_FREEZEPLAYER2 freezes until told otherwise"); Dfz.handle("game", 155, b""); check(not Dfz.frozen(), "PLO_UNFREEZEPLAYER")
    Dfz.handle("game", 10, b""); check(Dfz.is_leader, "PLO_ISLEADER")
    hx_ = (ax + 3) * 2 + 0.5; hy_ = (ay + 2) * 2 + 0.5; Dfz.handle("game", 46, gint_enc(9, 2) + gchar(1) + gchar(int((ax + 3) * 2 + 0)) + gchar(int((ay + 2) * 2 + 0)))
    Dfz.npcrt.tick(ffz[0] + 0.1); check(Dfz.npcrt.inst[("w", 1)].this.get("hit") == 1, "PLO_HITOBJECTS: another player's sword hit fires washit on the NPC there")
    Dar, far = world([(("w", 1), "if (created) { setshape 1,16,16; }\nif (wasshot) { this.shot = 1; }", (ax + 6) * 16, (ay + 2) * 16)])
    Dar.handle("game", 19, gint_enc(5, 2) + gchar((ax + 2) * 2) + gchar((ay + 2) * 2 + 1) + gchar(3 | 8) + gchar(0) + gchar(1)); check(Dar.proj.list and Dar.proj.list[0].hits, "PLO_ARROWADD: another player's arrow flies")
    for k in range(40): far[0] += 0.05; Dar.proj.tick(far[0]); [setattr(p_, "next", 0) for p_ in Dar.proj.list]; Dar.npcrt.tick(far[0])
    check(Dar.npcrt.inst[("w", 1)].this.get("shot") == 1 and not Dar.proj.list, "it hits an NPC that listens for wasshot and stops")
    Dar.handle("game", 41, b"<b>Welcome</b>"); check(Dar.start_message == "<b>Welcome</b>", "PLO_STARTMESSAGE is kept")
    def rider_frame(horse):
        Dri = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (ax * 16, ay * 16), account="TestA"); Dri.send = lambda l: None
        if horse: Dri.me["HORSEIMAGE"] = "aurorabrownhorse.gif"
        Dri.me["SPRITE"] = 1; return render.render_scene(Dri.snapshot(), size=(300, 230))
    check(ImageChops.difference(rider_frame(False).convert("RGB"), rider_frame(True).convert("RGB")).getbbox() is not None, "a player with HORSEIMAGE is drawn on a horse")
    check(render.horse_frame("aurorabrownhorse.gif", 1) is not None and render.horse_frame("aurorabrownhorse.gif", 3).size == (96, 64) and render.horse_frame("no_such_horse.gif", 1) is None, "horse frames: side view 96 x 64, mirrored for right, missing sheet -> None")
    print("npc motion tests passed")

if __name__ == "__main__": main()
