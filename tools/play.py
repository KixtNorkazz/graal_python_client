"""End-to-end demo against the local gserver: login -> load surroundings -> render -> chat -> walk -> level link -> render -> return.
Usage: GRAAL_PASSWORD=.. python3 play.py <output-dir> [--no-link]"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from gclient import *
import render

def snap(s, out, name):
    render.render_scene(s.snapshot(), t=time.time()).convert("RGB").save(os.path.join(out, name)); print("  saved", name)

def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True)
    s = Session("TestA", os.environ["GRAAL_PASSWORD"]); s.connect(); s.pump(1.5)
    start = (s.level_name, s.pos); print("logged in:", start, "cell", s.cell, "NPCs:", len(s.npcs))
    for n in ("a2 b2 c2 a3 c3 a4 b4 c4".split()):
        s.request_level(f"portwolfe_{n}.nw"); s.pump(0.2)
    s.pump(0.4); snap(s, out, "1_start.png")
    s.say("hello from the python client"); s.pump(0.4); snap(s, out, "2_chat.png")
    s.walk("U", 18); snap(s, out, "3_walked.png")
    s.clear_chat()
    if "--no-link" not in sys.argv:
        link = s.walk("R", 53)
        print("entered link:", link and link["level"], "->", s.level_name, "pos", s.pos)
        s.pump(1.5)
        if s.levels.get(s.level_name) and s.levels[s.level_name].board: snap(s, out, "4_inside.png")
        s.warp(*start[:1], *start[1]); s.pump(2.0)
    print("back at:", s.level_name, s.pos, "cell", s.cell)
    s.close()

main()
