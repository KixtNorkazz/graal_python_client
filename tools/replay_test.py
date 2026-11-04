"""Offline check: replay captured proxy logs (hex lines: 't cN C>S|S>C len hex') through graalproto."""
import sys, collections
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from graalproto import *

def run(path):
    conns = collections.defaultdict(list)
    for ln in open(path):
        p = ln.split()
        if len(p) >= 5 and p[2] in ("C>S", "S>C"): conns[p[1]].append((p[2], bytes.fromhex(p[4])))
    ok = bad = exact = 0
    for cid, msgs in conns.items():
        first = next(b for d, b in msgs if d == "C>S")
        import zlib; seed = zlib.decompress(first[2:2 + ((first[0] << 8) | first[1])])[1] - 0x20
        rx = {"C>S": Stream(seed, True), "S>C": Stream(seed)}
        tx = Stream(seed, True)
        wire = b""
        for d, b in msgs:
            if d == "C>S": wire += b
            for t, plain in rx[d].feed(b):
                ok += 1
                if d == "C>S":
                    if rx[d].login and t == 3: rx[d].login = False
                    re = tx.encode(plain, None if tx.login else t if t in (2, 4) else None)
                    tx.login = False
                    if t == 2:
                        exact += (re in wire); bad += (re not in wire)
    return ok, exact, bad

for f in sys.argv[1:]:
    ok, exact, bad = run(f)
    print(f"{f.rsplit('/',1)[-1]}: decoded {ok} frames, type-2 re-encodes byte-exact: {exact}, mismatched: {bad}")
