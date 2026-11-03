"""Log in (like minclient) and print every decoded server packet with its PLO name. Usage: GRAAL_PASSWORD=.. python3 trace.py TestA [seconds]"""
import os, sys, time, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graalproto import *
from minclient import Conn, list_servers, VERSIONS
import enums

acct, secs = sys.argv[1].encode(), float(sys.argv[2]) if len(sys.argv) > 2 else 4
pw = os.environ["GRAAL_PASSWORD"].encode()
servers, _ = list_servers("127.0.0.1", 9111, acct, pw, False)
host, port = servers[0]
g = Conn(host, port); v = VERSIONS["222"]
g.send(game_login(g.seed, v["game"], acct, pw)); g.send(language() + gline(39, v["id39"]))
lp = LineParser(); t0 = time.time()
for t, plain in g.frames(secs):
    print(f"--- frame type {t}, {len(plain)} bytes")
    for kind, pid, payload in lp.feed(plain):
        name = enums.PLO.get(pid, f"?{pid}")
        print(f"  {kind:4} {pid:3} {name:22} {len(payload):6}B  {payload[:90]!r}")
g.close()
