"""Dry run of the GS2 weapons of a level backup: created / playerenters / weaponfired / chat / timeout / actions.
python3 gs2weapons_survey.py  -> parse failures, event runs, logged errors, unsupported calls."""
import sys, os, re, glob, time, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import offline, gs2npc

import os, config
BASE = config.dirs("weapon_dirs")[0] + os.sep

def script_of(t):
    m = re.search(r"^SCRIPT\n(.*?)^SCRIPTEND", t, re.S | re.M); return m.group(1) if m else t

if __name__ == "__main__":
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500)); s.level_name = "laboo-mountain_a1.nw"
    names = []
    for p in sorted(glob.glob(BASE + "/*")):
        t = open(p, encoding="latin1").read(); sc = script_of(t)
        if gs2npc.is_gs2(sc): s.runner.add(os.path.basename(p)[:40], "", sc); names.append(os.path.basename(p)[:40])
    parsed = [w for w in s.runner.weapons.values() if w.gs2]; runs = 0; now = time.time()
    print(len(names), "GS2 weapons,", len(parsed), "parsed;", [l for l in s.log if "parse" in l][:3])
    for w in parsed:
        for ev in ("created", "playerenters", "weaponfired", "playerchats", "timeout", "actionfoo"):
            if w.gs2.has_function("on" + ev): s.runner.run_event(w, ev, "/test"); runs += 1
    for k in range(40):
        s.runner.tick(now + k * 0.1)
        for w in parsed: w.tasks = [(0, g) for _, g in w.tasks]; w.timeout_at = now + k * 0.1 if w.timeout_at else None
    errs = [l for l in s.log if l.startswith("gs2 weapon")]
    print(runs, "event runs,", len(errs), "errors"); [print("  ", e[:160]) for e in errs[:8]]
    print("unsupported:", collections.Counter(s.unsupported).most_common(25))
