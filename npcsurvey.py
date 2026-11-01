"""Dry run: level NPC scripts of a level backup through created / timeout / playertouchsme / playerchats.
python3 npcsurvey.py [max_levels]  -> exceptions, event runs, unsupported commands."""
import sys, os, time, random, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets, offline, nwlevel, gs2npc

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500; only_gs2 = "--gs2" in sys.argv
    files = sorted(p for k, p in assets.index().items() if k.endswith(".nw")); random.Random(1).shuffle(files)
    unsup = collections.Counter(); runs = errs = lv_n = npcs = gs2n = 0; t0 = time.time(); worst = []
    for p in files:
        if lv_n >= limit: break
        try: nw = nwlevel.load_nw(p)
        except Exception: continue
        if not any(n["script"].strip() for n in nw.npcs): continue
        if only_gs2 and not any(gs2npc.is_gs2(n["script"]) for n in nw.npcs): continue
        lv_n += 1
        try: s = offline.OfflineSession(os.path.basename(p), pos=(480, 480))
        except Exception as e: errs += 1; print("session", p, repr(e)); continue
        t1 = time.time()
        for nid, n in list(s.npcs.items()):
            npcs += 1; s.npcrt.fx(nid, n)
        now = time.time()
        for step in range(40):
            if step == 10: s.npcrt.broadcast("playertouchsme"); s.npcrt.broadcast("playerchats", "hello")
            s.npcrt.tick(now + step * 0.05)
            for i in s.npcrt.inst.values():
                i.tasks = [(0, g) for _, g in i.tasks]
        errs += s.npcrt.errors; g2 = sum(1 for i in s.npcrt.inst.values() if i.gs2); gs2n += g2
        for l in s.log:
            if l.startswith("npc "): print(os.path.basename(p), l[:150])
        for k, v in s.unsupported.items(): unsup[k] += v
        d = time.time() - t1; worst.append((d, os.path.basename(p)))
    print(f"{lv_n} levels, {npcs} npcs ({gs2n} GS2), {errs} errors, {time.time() - t0:.1f}s; slowest {sorted(worst)[-3:]}")
    print("unsupported:", unsup.most_common(25))
