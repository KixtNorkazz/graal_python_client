import os, sys, collections, runpy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import weapons
fails = collections.Counter(); ex = {}
orig_eval = eval
def patched(e, env=None, *a):
    try: return orig_eval(e, env, *a)
    except Exception as x:
        fails[type(x).__name__ + ": " + e[:70]] += 1; raise
weapons.eval = patched
sys.argv = ["npcsurvey.py"]
try: runpy.run_path(os.path.dirname(os.path.abspath(__file__)) + "/npcsurvey.py", run_name="__main__")
except SystemExit: pass
print(sum(fails.values()), len(fails))
for k, n in fails.most_common(40): print(n, k)
