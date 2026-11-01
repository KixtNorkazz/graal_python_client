"""Usage survey of compiled GS2 bytecode: event handlers, called built-ins (callee not defined in the script), member names and objects.
python3 gs2survey.py file.gs2bc ...   (prints counts)"""
import collections, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gs2dis

def survey(paths):
    events, builtins, methods, objects, ops = (collections.Counter() for _ in range(5))
    for p in paths:
        r = gs2dis.disassemble(open(p, "rb").read()); ops_ = r["ops"]; defined = {n for _, n in r["functions"]}
        for _, n in r["functions"]:
            if n.startswith("on"): events[n] += 1
        for k, (n, off, name, operand) in enumerate(ops_):
            ops[name] += 1
            if name in ("OP_THIS", "OP_THISO", "OP_PLAYER", "OP_PLAYERO", "OP_LEVEL", "OP_TEMP"): objects[name[3:].lower()] += 1
            if name == "OP_CALL":
                j = k - 1
                member = False
                while j >= 0 and ops_[j][2] in ("OP_MEMBER_ACCESS", "OP_CONV_TO_OBJECT", "OP_INDEX_DEC"):
                    member |= ops_[j][2] == "OP_MEMBER_ACCESS"; j -= 1
                if j >= 0 and ops_[j][2] == "OP_TYPE_VAR" and ops_[j][3]:
                    nm = ops_[j][3][2]
                    if nm in defined: continue
                    (methods if member else builtins)[nm] += 1
    return events, builtins, methods, objects, ops

if __name__ == "__main__":
    ev, bi, me, ob, ops = survey(sys.argv[1:])
    for title, c in (("events", ev), ("built-in functions", bi), ("methods", me), ("objects", ob)):
        print(f"{title} ({len(c)} distinct):", ", ".join(f"{k}x{v}" for k, v in c.most_common(40)))
    print("opcodes used:", len(ops), "of", len(gs2dis.OPS))
