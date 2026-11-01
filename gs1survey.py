"""GS1 command frequency survey over a Graal server backup.
python3 gs1survey.py <backup_root>  -> counts of statement commands in weapons/npcs/scripts files and in level (.nw) NPC blocks."""
import collections, os, re, sys

IMPLEMENTED = {"changeimgmode", "stopsound", "setfocus", "resetfocus", "putbomb", "return", "shoot", "setshootparams", "showpoly", "hidepoly", "wraptext2", "setgifpart", "seteffectmode", "timereverywhere", "play", "playlooped", "stopmidi",
    "setimg", "setgif", "setimgpart", "drawoverplayer", "drawunderplayer", "drawaslight", "setzoomeffect", "setcoloreffect", "hide", "show",
    "showimg", "changeimgvis", "changeimgcolors", "changeimgzoom", "changeimgpart", "showcharacter", "setcharani", "setcharprop",
    "addtiledef", "addtiledef2", "dontblock", "setshape", "setshape2", "setani", "replaceani", "freezeplayer", "setstring", "setplayerprop", "sleep",
    "triggeraction", "join", "set", "unset", "tokenize", "addstring", "deletestring", "setarray", "say2", "showtext", "destroy", "seteffect",
    "setskincolor", "setcoatcolor", "setsleevecolor", "setshoecolor", "setbeltcolor", "enabledefmovement", "disabledefmovement", "hideimg", "hideimgs"}
CONTROL = {"if", "else", "while", "for", "return", "break", "continue", "switch", "case", "default", "function", "with", "do"}

def commands(script):
    s = re.sub(r"//[^\n]*", "", script)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r'"[^"]*"', '""', s)
    for st in re.split(r"[;{}]", s):
        st = st.strip()
        m = re.match(r"([A-Za-z_]\w*)\b(?!\s*(?:\.|=(?!=)|\+=|-=|\+\+|--))", st)
        if m and m.group(1).lower() not in CONTROL:
            yield m.group(1).lower()

def scripts(root):
    for d in ("weapons", "npcs", "scripts", "scriptfiles"):
        p = os.path.join(root, d)
        for dp, dn, fn in os.walk(p):
            for f in fn:
                if f.lower().endswith((".txt", ".nw")) :
                    try: yield f"{d}/{f}", open(os.path.join(dp, f), encoding="latin1").read()
                    except OSError: pass
    lv = os.path.join(root, "levels")
    for dp, dn, fn in os.walk(lv):
        for f in fn:
            if f.lower().endswith(".nw"):
                try: t = open(os.path.join(dp, f), encoding="latin1").read()
                except OSError: continue
                for m in re.finditer(r"^NPC\b[^\n]*\n(.*?)^NPCEND", t, re.S | re.M): yield f"levels/{f}", m.group(1)

if __name__ == "__main__":
    root = sys.argv[1]; cnt = collections.Counter(); files = collections.defaultdict(set); n = 0
    for name, text in scripts(root):
        n += 1
        for c in commands(text): cnt[c] += 1; files[c].add(name)
    total = sum(cnt.values()); done = sum(v for k, v in cnt.items() if k in IMPLEMENTED)
    print(f"{n} script bodies, {total} command statements, {len(cnt)} distinct commands; implemented: {done} ({100 * done // max(total, 1)}%)")
    print("top commands (* = implemented):")
    for k, v in cnt.most_common(70): print(f"  {'*' if k in IMPLEMENTED else ' '} {k:22} {v:7}  in {len(files[k])} files")
