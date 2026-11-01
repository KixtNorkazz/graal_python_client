"""python3 walk_survey.py [levels] -> random walks in real RP server levels on a virtual clock: exceptions, results (arrived / blocked / timeout), time per plan."""
import sys, os, time, random, collections, traceback
import assets, nwlevel, offline

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40; rnd = random.Random(7)
    files = sorted(p for k, p in assets.index().items() if k.endswith(".nw")); rnd.shuffle(files)
    res = collections.Counter(); errs = 0; worst = (0, ""); done = 0
    for p in files:
        if done >= n: break
        try: nw = nwlevel.load_nw(p)
        except Exception: continue
        if not any(x["script"].strip() for x in nw.npcs): continue
        done += 1; name = os.path.basename(p)
        try:
            s = offline.OfflineSession(name, pos=(480, 480)); s.send = lambda l: None; fk = [time.time()]; s.clock = lambda: fk[0]
            free = [(x, y) for x in range(16, 1008, 16) for y in range(16, 1008, 16) if not s.coll.blocked(s, x, y)]
            if len(free) < 40: res["tiny level"] += 1; continue
            s.pos = rnd.choice(free); goal = rnd.choice(free)
            t0 = time.time(); ok = s.walk_to(goal[0] / 16, goal[1] / 16); dt = time.time() - t0
            if dt > worst[0]: worst = (dt, name)
            if not ok: res["no path"] += 1; continue
            for _ in range(1200):
                fk[0] += 0.05; s.npcrt.tick(fk[0]); s.bombs.tick(fk[0]); s.proj.tick(fk[0]); s._mission_tick(fk[0]); s._carry_tick(); s.death_tick()
                if s.walk_task: s._walk_tick(fk[0])
                if not s.walking_to(): break
            res[s.walk_result if not s.walking_to() else "timeout"] += 1
        except Exception:
            errs += 1; print("ERR", name); traceback.print_exc(limit=3)
    print(f"{done} levels, {errs} errors, results {dict(res)}, slowest plan {worst[0]:.2f}s ({worst[1]})")

if __name__ == "__main__": main()
