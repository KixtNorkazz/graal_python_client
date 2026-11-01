"""python3 run_tests.py [--quick]  -> every test file and survey with a one-line verdict; exit status 1 when anything failed.
--quick skips the slow corpus surveys. Live tests (simulate_two.py, needs GRAAL_PASSWORD and the running server) are only run with --live."""
import subprocess, sys, time, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = ["test_npcmotion", "test_walk", "test_npcserver", "test_gs2src", "test_gui", "test_inputs", "test_config", "test_login_gui", "test_filefetch", "test_inventory", "test_messagebox", "test_chatline", "test_tiledefs"]
SURVEYS = [("gs2weapons_survey.py", [], r"(\d+) event runs, (\d+) errors", 2), ("npcsurvey.py", ["100"], r"(\d+) levels, (\d+) npcs.*?(\d+) errors", 3),
           ("walk_survey.py", ["30"], r"(\d+) levels, (\d+) errors", 2)]

def run(cmd, env=None, timeout=900):
    t0 = time.time(); p = subprocess.run([sys.executable] + cmd, cwd=HERE, capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout + p.stderr), time.time() - t0

def main():
    quick = "--quick" in sys.argv; live = "--live" in sys.argv; bad = 0
    for t in TESTS:
        rc, out, dt = run([t + ".py"]); ok = rc == 0 and "passed" in out.splitlines()[-1] if out.strip() else False
        print(f"{'ok  ' if ok else 'FAIL'} {t:18s} {dt:6.1f}s  {out.strip().splitlines()[-1][:80] if out.strip() else ''}"); bad += not ok
        if not ok: print(out[-1500:])
    if not quick:
        for script, args, pat, errgroup in SURVEYS:
            rc, out, dt = run([script] + args); m = re.search(pat, out)
            ok = bool(m) and int(m.group(errgroup)) == 0
            print(f"{'ok  ' if ok else 'FAIL'} {script:22s} {dt:6.1f}s  {m.group(0)[:70] if m else out[-200:]}"); bad += not ok
    if live:
        env = dict(os.environ); rc, out, dt = run(["simulate_two.py"], env=env, timeout=600); ok = "RESULT: ok" in out
        print(f"{'ok  ' if ok else 'FAIL'} simulate_two (live)   {dt:6.1f}s"); bad += not ok
    print("ALL OK" if not bad else f"{bad} FAILED"); sys.exit(1 if bad else 0)

if __name__ == "__main__": main()
