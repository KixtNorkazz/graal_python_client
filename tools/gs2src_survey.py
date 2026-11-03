"""Survey of GS2 *source* scripts (NPCs in .nw levels): which events, calls and syntax they use.  python3 gs2src_survey.py <root>"""
import collections, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
root = sys.argv[1]; ev = collections.Counter(); calls = collections.Counter(); syn = collections.Counter(); n = 0; sizes = []
for dp, dn, fn in os.walk(root):
    for f in fn:
        if not f.lower().endswith(".nw"): continue
        try: t = open(os.path.join(dp, f), encoding="latin1").read()
        except OSError: continue
        for m in re.finditer(r"^NPC\b[^\n]*\n(.*?)^NPCEND", t, re.S | re.M):
            b = re.sub(r"//[^\n]*", "", m.group(1)); b = b[re.search(r"//#CLIENTSIDE", m.group(1)).end():] if "//#CLIENTSIDE" in m.group(1) else b
            if not re.search(r"\bfunction\s+\w+\s*\(", b): continue
            if not re.search(r"\bfunction\s+on[A-Z]\w*\s*\(", b): continue
            n += 1; sizes.append(len(b))
            for e in re.findall(r"\bfunction\s+(on\w+)", b): ev[e] += 1
            for c in re.findall(r"(?<![\w.])([A-Za-z_]\w*)\s*\(", b):
                if c not in ("if", "while", "for", "function", "switch", "return") and not c.startswith("on"): calls[c] += 1
            for c in re.findall(r"\.([A-Za-z_]\w*)\s*\(", b): calls["." + c] += 1
            for k in ("temp.", "this.", "player.", "with (", "with(", "new ", "foreach", "}.", " in ", "@", "%", "echo(", "sleep(", "scheduleevent", "setTimer", "class", "public", "{ }"):
                if k in b: syn[k] += 1
print(n, "gs2 NPC scripts, median size", sorted(sizes)[len(sizes) // 2], "max", max(sizes))
print("events:", ev.most_common(25)); print("syntax:", syn.most_common(20)); print("calls:", calls.most_common(70))
