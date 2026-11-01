"""python3 test_inputs.py : keyboard / mouse state and events for GS1 and GS2 scripts (offline, no SDL window)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline, inputs

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    check(inputs.sdl_to_vk(ord("h")) == 72 and inputs.sdl_to_vk(ord("1")) == 49 and inputs.sdl_to_vk(9) == 9 and inputs.sdl_to_vk(ord("`")) == 192 and inputs.sdl_to_vk(ord("=")) == 187, "VK codes")
    check(inputs.sdl_to_vk(0x40000045) == 123 and inputs.sdl_to_vk(0x4000_0052) == 38 and inputs.sdl_to_vk(0x4000_00E0) == 0, "F12 = VK 123, unknown special keys = 0")
    s = offline.OfflineSession("turtlejunction-.gmap", (7, 3), (500, 500))
    src = """//#CLIENTSIDE
function onKeyPressed(code, key) { client.k = code @ ":" @ key; if (key == "h") client.h += 1; if (keydown(5)) client.sdown = 1; }
function onKeyUp(code, key) { client.up = key; }
function onMouseDown(mode) { client.m = mode; client.mx = int(mousex); client.msx = mousescreenx; }
function onMouseUp() { client.mu = params[0]; }
"""
    s.runner.add("-Keys", "", src)
    s.input.key(ord("h"), True); check(s.gs2_client["k"] == "72:h" and s.gs2_client["h"] == 1.0, f"onKeyPressed {s.gs2_client}")
    s.input.key(ord("s"), True); check(s.input.is_down(5) and s.gs2_client["sdown"] == 1.0, "keydown(5) while S is held (GS2 builtin)")
    s.input.key(ord("s"), False); check(not s.input.is_down(5), "key release")
    s.input.key(0x4000_0052, True); check(s.input.is_down(0), "arrow up = keydown(0)")
    s.input.key(ord("h"), False); check(s.gs2_client["up"] == "h", "onKeyUp")
    s.input.mouse_button(1, True, 320, 228)
    check(s.gs2_client["m"] == "left" and s.gs2_client["msx"] == 320.0 and s.gs2_client["mx"] == 32, f"onMouseDown {s.gs2_client} world {s.input.world()}")
    check(abs(s.input.world()[0] - 32.75) < 1e-6 and abs(s.input.world()[1] - 32.75) < 1e-6, "mouse world position")
    s.input.mouse_button(1, False); check(s.gs2_client["mu"] == "left" and not s.input.button("left"), "onMouseUp / params[0]")
    gs1 = "if (mousedown && leftmousebutton) { setstring clicked,yes; }\nif (mouseup && mousescreenx in |100,200|) { setstring released,yes; }\nif (timeout) { if (keydown(6)) setstring dkey,yes; timeout = .05; }\nif (created) { timeout = .05; }"
    s.npcs[("t", 1)] = dict(IMAGE="x.png", SCRIPT=gs1, X2=160, Y2=160, GMAPLEVELX=7, GMAPLEVELY=3, LEVEL="turtlejunction-h4.nw")
    inst = s.npcrt.instance(("t", 1), s.npcs[("t", 1)])
    s.input.mouse_button(1, True, 150, 100); check(s.vars.get("clicked") == "yes", f"GS1 mousedown&&leftmousebutton {s.vars}")
    s.input.mouse_button(1, False, 150, 100); check(s.vars.get("released") == "yes", "GS1 `mousescreenx in |100,200|` on mouseup")
    s.input.mouse_button(3, True, 10, 10); s.vars.pop("clicked", None)
    s.input.mouse_button(3, False); s.input.mouse_button(3, True); check("clicked" not in s.vars, "right button is not leftmousebutton")
    s.input.key(ord("d"), True); s.npcrt.tick(time.time() + 0.1); check(s.vars.get("dkey") == "yes", "GS1 keydown(6) = D")
    print("input tests passed")

if __name__ == "__main__": main()
