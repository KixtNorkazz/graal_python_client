"""python3 test_gs2src.py : language-level checks for gs2src.py (no network, no assets) plus NPC behaviour checks on offline sessions."""
import math, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gs2src
from gs2src import Interp, Obj, DictObj

class Host:
    def __init__(self): self.props = {"x": 3.0, "y": 4.0}; self.calls = []; self.unk = []
    def global_obj(self, low): return None
    def has_prop(self, low): return low in self.props
    def get_prop(self, low): return self.props[low]
    def set_prop(self, low, v): self.props[low] = v
    def call(self, name, args, interp): self.calls.append((name, args)); return None
    def unknown(self, name): self.unk.append(name)

def run(src, event="onCreated", host=None):
    h = host or Host(); it = Interp(h, src); delays = list(it.call_function(event)); return it, h, delays

def check(cond, msg):
    if not cond: raise AssertionError(msg)

def main():
    it, h, d = run("function onCreated() { this.a = 2 + 3 * 4; this.s = \"x\" @ 1 SPC 2; this.t = 7 % 4; this.p = 2 ^ 3; }")
    check(it.this.d["a"] == 14.0 and it.this.d["s"] == "x1 2" and it.this.d["t"] == 3.0 and it.this.d["p"] == 8.0, "arith/concat")
    it, h, d = run("function onCreated() { for (temp.i = 0; temp.i < 5; temp.i++) { if (temp.i == 3) continue; this.n += temp.i; } while (this.n < 20) this.n += 5; }")
    check(it.this.d["n"] == 22.0, f"loops {it.this.d}")
    it, h, d = run("function onCreated() { temp.arr = {1, 2, {3, 4}}; foreach (v : temp.arr) { if (v == 2) break; this.c += 1; } this.len = temp.arr.size(); }")
    check(it.this.d["c"] == 1.0 and it.this.d["len"] == 3.0, "foreach/break/size")
    it, h, d = run("function onCreated() { sleep(.5); this.a = 1; sleep(2); this.b = 2; }")
    check(d == [0.5, 2.0] and it.this.d == {"a": 1.0, "b": 2.0}, f"sleep {d}")
    it, h, d = run("function f(a, b) { return a * b; } function onCreated() { this.r = f(3, 4); this.q = fib(10); } function fib(n) { if (n < 2) return n; return fib(n-1) + fib(n-2); }")
    check(it.this.d["r"] == 12.0 and it.this.d["q"] == 55.0, f"functions {it.this.d}")
    it, h, d = run("function onCreated() { x = 10, y = x + 1; this.k = x in |5, 12|; this.z = true ? \"yes\" : \"no\"; }")
    check(h.props["x"] == 10.0 and h.props["y"] == 11.0 and it.this.d["k"] == 1.0 and it.this.d["z"] == "yes", f"props/in/ternary {h.props} {it.this.d}")
    it, h, d = run("function onCreated() { switch (this.v) { case 1: this.r = \"one\"; break; default: this.r = \"other\"; } switch (\"B\") { case \"b\": this.s = 1; } }")
    check(it.this.d["r"] == "other" and it.this.d["s"] == 1.0, f"switch {it.this.d}")
    it, h, d = run("function onCreated() { setimgpart(\"a.png\", 0, 1, 2, 3); doesnotexist(1); }")
    check(h.calls[0] == ("setimgpart", ["a.png", 0.0, 1.0, 2.0, 3.0]) and len(h.calls) == 2, f"host bridge {h.calls}")
    it, h, d = run("function onCreated() { onTimeOut(); } function onTimeOut() { this.t += 1; } function onTimeOut() { this.t += 10; }")
    check(it.this.d["t"] == 11.0, "joined/duplicate definitions chain")
    try: run("function onCreated() { while (true) { this.a += 1; } }"); check(False, "infinite loop must stop")
    except gs2src.Gs2Error: pass
    check(gs2src.equal("Abc", "aBC") and not gs2src.equal("a", "b") and gs2src.equal("1.0", 1.0), "case-insensitive string equality")
    import offline, time
    s = offline.OfflineSession("bd_house-basement.nw")
    k = next(k for k, n in s.npcs.items() if "bookshelf3" in n["SCRIPT"] and "function onCreated" in n["SCRIPT"]); i = s.npcrt.inst[k]
    check(i.gs2 and i.fx.imgpart == ("longfellow-bookshelf3.gif", 0, 0, 99, 112) and i.fx.shape[:3] == ("grid", 5, 6), "setimgpart/setshape2 from onCreated")
    s = offline.OfflineSession("val-wizardtoweralkarillusion.nw")
    k = next(k for k, n in s.npcs.items() if "findimg(300)" in n["SCRIPT"]); i = s.npcrt.inst[k]
    sh = i.fx.shows[300]; r0 = sh["rot"]
    for st in range(5): s.npcrt.tick(time.time() + st * 0.06); i.tasks = [(0, g) for _, g in i.tasks]
    check(sh["image"] == "val-shivaldoll1.gif" and (sh["x"], sh["y"]) == (48.0, 11.0) and sh["rot"] != r0, f"findimg/with/setTimer {sh}")
    s = offline.OfflineSession("inquisition_b2.nw")
    k = next(k for k, n in s.npcs.items() if "midday" in n["SCRIPT"]); s.npcrt.broadcast("playerchats", "evening")
    check(s.effect == (0.0, 0.05, 0.1, 0.5), f"onPlayerChats + seteffect {s.effect}")
    import particles
    e = particles.Emitter(); e.pdef.update(image="x.png", lifetime=2.0, speed=10.0, angle=math.pi / 2); e.cfg.update(delaymin=0.1, delaymax=0.1, nrofparticles=2)
    e.add_modifier("local", "once", 0, 0, "x", "add", -1.5, 1.5); e.add_modifier("local", "range", 0, 2, "alpha", "replace", 1.0, 0.0)
    e.add_modifier("global", "impulse", 0.2, 0.2, "speed", "multiply", 0.5, 0.5)
    for _ in range(20): e.update(0.05, (100.0, 100.0))
    old = min(e.particles, key=lambda p: -p["age"])
    check(len(e.particles) > 5 and old["y"] < 100.0 and 0.0 <= old["alpha"] < 1.0 and old["speed"] < 10.0, f"particle emitter {old}")
    e.cfg["isfrozen"] = 1.0; n0 = len(e.particles); e.update(0.05, (100.0, 100.0)); check(len(e.particles) <= n0, "isfrozen stops emission")
    s = offline.OfflineSession("iraq.nw")
    k = next(k for k, n in s.npcs.items() if "emitter" in n["SCRIPT"] and "g4_particle_bubble" in n["SCRIPT"]); sh = s.npcrt.inst[k].fx.shows
    em = next(v["em"] for v in sh.values() if "em" in v)
    check(em.pdef["image"] == "g4_particle_bubble.png" and len(em.locals) >= 5 and len(em.globals) == 1, f"emitter configured by GS2 script {em.pdef} {len(em.locals)}")
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500)); sent = []; s.send = lambda l: sent.append(l)
    s.npcserver.enabled = False
    src = """//#CLIENTSIDE
function onWeaponFired() {
  setani("sword", "");
  shoot(player.x, player.y, 0, getangle(vecx(player.dir), vecy(player.dir)), 0, 0, "val-fire-ball", 1);
  this.fired += 1;
  sleep(.1);
  play("pound.wav");
  setTimer(.2);
}
function onTimeOut() { this.timeouts += 1; triggerserver("gui", "Test", "ping", this.timeouts); }
function onPlayerChats() { client.heard = player.chat; }
function onActionFoo(a, b) { client.foo = a @ "-" @ b; }
"""
    s.runner.add("Test", "", src); w = s.runner.weapons["Test"]
    check(w.gs2 and s.runner.firable() == [w], "GS2 weapon detected and firable")
    s.runner.fire(0)
    check(len(s.proj.list) == 1 and w.gs2.this.d["fired"] == 1.0, f"onWeaponFired ran (shoot + this) {s.log}")
    check(not any(p[0] == "pound.wav" for p in s.audio.played) and w.tasks, "sleep() suspended the event")
    s.runner.tick(time.time() + 0.2)
    check(any(p[0] == "pound.wav" for p in s.audio.played) and w.timeout_at, "after sleep: play + setTimer")
    s.runner.tick(time.time() + 1.0)
    check(w.gs2.this.d["timeouts"] == 1.0 and any(b"serverside" in x and b"ping" in x for x in sent), f"onTimeOut + triggerserver {sent[-1:]}")
    s.runner.broadcast("playerchats", chat="hello"); check(s.gs2_client["heard"] == "hello", "onPlayerChats")
    s.runner.broadcast("actionfoo", params=["1", "2"]); check(s.gs2_client["foo"] == "1-2", "onActionFoo(params)")
    check(s.me.get("GANI", "").startswith("sword"), f"setani via bridge {s.me.get('GANI')}")
    import os, config, re, gs2src as _g
    wsrc = open(os.path.join(config.dirs("weapon_dirs")[0], "weapon%045Temp%095LabooWeather.txt"), encoding="latin1").read()
    sc = re.search(r"^SCRIPT\n(.*?)^SCRIPTEND", wsrc, re.S | re.M).group(1)
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500)); s.level_name = "laboo-mountain_a1.nw"
    s.runner.add("-Temp_LabooWeather", "", sc); w = s.runner.weapons["-Temp_LabooWeather"]
    _g.REAL_RANDOM[0] = True; s.runner.run_event(w, "created"); s.runner.run_event(w, "playerenters"); t0 = time.time()
    for k in range(10): s.runner.tick(t0 + k * 0.06); w.timeout_at = (t0 + k * 0.06) if w.timeout_at else None
    check(len(s.imgs) == 200 and len({(round(v["x"]), round(v["y"])) for v in s.imgs.values()}) > 150 and s.imgs[200]["image"] == "val_frost-snowflake.gif", f"snow weapon {len(s.imgs)}")
    s.level_name = "somewhere.nw"; s.runner.run_event(w, "playerenters"); check(len(s.imgs) == 0 and w.timeout_at is None, "leaving the snow level hides the flakes")
    _g.REAL_RANDOM[0] = False
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500))
    s.runner.add("-+Util", "", """//#CLIENTSIDE
enum { M_A, M_B = 5, M_C }
function onCreated() { Util = this; this.mode = M_C; this.added = join("util_sleep2"); }
public function double(v) { return v * 2; }
public function run(fname, v) { return makevar(fname)(v); }
""")
    s.runner.add("-+User", "", """//#CLIENTSIDE
function onCreated() {
  this.a = Util.double(21);
  this.b = Util.run("double", 4);
  this.c = Util.mode;
  this.d = Util.hasfunction("run") @ Util.hasfunction("nope");
  new TStaticVar("Bag").x = 7;
  this.e = new TStaticVar("Bag").x;
}
""")
    u, w2 = s.runner.weapons["-+Util"].gs2.this, s.runner.weapons["-+User"].gs2.this
    check(u.d["mode"] == 6.0, f"enum M_B = 5 then M_C = 6: {u.d}")
    check((w2.d["a"], w2.d["b"], w2.d["c"], w2.d["d"], w2.d["e"]) == (42.0, 8.0, 6.0, "10", 7.0), f"classes {w2.d}")
    check("sleep2" in s.runner.weapons["-+Util"].gs2.funcs, "join() added the class functions")
    check(u.get("name") == "-+Util", "this.name")
    print("gs2src tests passed")

if __name__ == "__main__": main()
