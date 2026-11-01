"""Minimal Graal 2.x client: logs in to the listserver, picks a server from the list, logs in to the gserver and
prints what comes back for a few seconds. Mimics Graal_222 (default) or Graal_231 on the wire.

  GRAAL_PASSWORD=... python3 minclient.py --account TestA [--listserver 127.0.0.1:9111] [--version 222|231]
                                           [--game-host HOST] [--seconds 8] [--walk L6,R6] [-v]
--walk is a comma list of <U|L|D|R><steps> (8 px per step, 50 ms apart); the client then idles and disconnects.
"""
import argparse, collections, getpass, os, random, re, socket, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graalproto import *

VERSIONS = {
    "222": dict(game=b"GNW03014", id39=bytes.fromhex("250e4d0f962b03ede631")),
    "231": dict(game=b"GNW28015", id39=bytes.fromhex("291655b7602e87c9eb82")),
}


class Conn:
    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.seed = random.randrange(128)
        self.tx, self.rx = Stream(self.seed, True), Stream(self.seed)

    def send(self, plain):
        self.sock.sendall(self.tx.encode(plain))
        self.tx.login = False

    def frames(self, timeout):
        """Yield (type, plain) for frames arriving within `timeout` seconds; stops on idle/close."""
        end = time.time() + timeout
        while time.time() < end:
            self.sock.settimeout(max(0.05, end - time.time()))
            try: data = self.sock.recv(65536)
            except socket.timeout: return
            if not data: return
            yield from self.rx.feed(data)

    def close(self): self.sock.close()


def find_endpoint(line):
    """Server-list lines end with gstr(host) + gstr(port)."""
    for k in range(len(line)):
        n = line[k] - 0x20
        host, rest = line[k + 1:k + 1 + n], line[k + 1 + n:]
        if (host and re.fullmatch(rb"[A-Za-z0-9._-]+", host) and rest
                and rest[0] - 0x20 == len(rest) - 1 and rest[1:].isdigit()):
            return host.decode(), int(rest[1:])
    return None


def parse_server_entry(line):
    """A list-server line: gchar(servers) { gchar(fields) gstr x fields }: name (with a type letter in front), language, description, url, version, players, host, port."""
    out, i = [], 1
    try:
        for _ in range(line[0] - 0x20):
            nf = line[i] - 0x20; i += 1; f = []
            for _ in range(nf):
                n = line[i] - 0x20; f.append(line[i + 1:i + 1 + n].decode("latin1")); i += 1 + n
            name = f[0][2:] if len(f[0]) > 2 and f[0][1] == " " else f[0]
            out.append(dict(name=name, language=f[1], description=f[2], url=f[3], version=f[4], players=f[5], host=f[6], port=int(f[7])))
    except (IndexError, ValueError):
        ep = find_endpoint(line)
        if ep and not out: out.append(dict(name=ep[0], language="", description="", url="", version="", players="", host=ep[0], port=ep[1]))
    return out


def list_servers_full(host, port, account, password, verbose):
    c = Conn(host, port)
    c.send(listserver_hello(c.seed))
    c.send(listserver_login(account, password))
    infos, notes = [], []
    for t, plain in c.frames(3):
        for pid, payload in split_lines(plain):
            if verbose: print(f"  list S>C id={pid} {payload[:70]!r}")
            if pid == 0: infos += parse_server_entry(payload)
            else: notes.append((pid, payload))
    c.close()
    return infos, notes


def list_servers(host, port, account, password, verbose):
    infos, notes = list_servers_full(host, port, account, password, verbose)
    return [(i["host"], i["port"]) for i in infos], notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--listserver", default="127.0.0.1:9111")
    ap.add_argument("--version", choices=VERSIONS, default="222")
    ap.add_argument("--game-host", help="override the host from the server list")
    ap.add_argument("--seconds", type=float, default=8)
    ap.add_argument("--walk", default="", help="e.g. L6,R6")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    pw = os.environ.get("GRAAL_PASSWORD") or getpass.getpass("Password: ")
    account, password = a.account.encode(), pw.encode()
    ls_host, ls_port = a.listserver.rsplit(":", 1)
    v = VERSIONS[a.version]

    servers, notes = list_servers(ls_host, int(ls_port), account, password, a.verbose)
    for pid, payload in notes:
        if pid == 2: print("listserver:", payload.decode("latin1").strip())
    if not servers:
        sys.exit("no server in the list (wrong account/password?)")
    host, port = servers[0]
    print(f"server list: {servers}")
    if a.game_host: host = a.game_host

    g = Conn(host, port)
    print(f"connected to gserver {host}:{port}, seed={g.seed}")
    g.send(game_login(g.seed, v["game"], account, password))
    g.send(language() + gline(39, v["id39"]))

    st = dict(level=None, board=None, links=0, pos=None, ids=collections.Counter(), frames=0, welcome=None, other=0)
    lp, timers = LineParser(), dict(hb39=time.time() + 3.2, hb24=time.time() + 5.1)

    def pump(timeout):
        for t, plain in g.frames(timeout):
            st["frames"] += 1
            for kind, pid, payload in lp.feed(plain):
                if kind == "raw":
                    if pid == 101 and len(payload) == 8192: st["board"] = payload
                    continue
                st["ids"][pid] += 1
                if a.verbose: print(f"  S>C id={pid} {payload[:60]!r}")
                if pid == 6 and payload.endswith(b".nw"): st["level"] = payload.decode()
                elif pid == 1: st["links"] += 1
                elif pid == 9:
                    m = list(re.finditer(rb"n([\x20-\xff]{2})o([\x20-\xff]{2})", payload))
                    if m and PROP_X2 and (m[-1].group(1)[0] - 0x20) < 32:
                        st["pos"] = (prop_x2(m[-1].group(1)), prop_x2(m[-1].group(2)))
                elif pid == 8: st["other"] += 1
                if b"Welcome" in payload and st["welcome"] is None: st["welcome"] = payload

    def heartbeat():
        now = time.time()
        if now >= timers["hb39"]: g.send(gline(39, v["id39"])); timers["hb39"] = now + 3.2
        if now >= timers["hb24"]: g.send(gline(24, gchar(9))); timers["hb24"] = now + 5.1

    pump(1.5)
    print(f"level: {st['level']}  board: {'%d tiles, %d non-zero' % (4096, sum(1 for i in range(0, 8192, 2) if st['board'][i] or st['board'][i+1])) if st['board'] else 'not received'}"
          f"  links: {st['links']}  own position (px): {st['pos']}")
    g.send(initial_props())
    x, y = (st["pos"][0], st["pos"][1]) if st["pos"] else (None, None)
    if a.walk and x is None: print("no own position from server; not walking"); a.walk = ""
    for seg in filter(None, a.walk.split(",")):
        d, n = seg[0].upper(), int(seg[1:])
        for line, x, y in walk_lines(d, n, x, y):
            g.send(line); heartbeat(); pump(0.05)
        g.send(idle_line())
        print(f"walked {seg}: now at {(x, y)} px")
        pump(0.2)
    end = time.time() + a.seconds
    while time.time() < end: heartbeat(); pump(0.3)
    g.close()
    print(f"frames: {st['frames']}  server line ids: {sorted(st['ids'].items())[:40]}  other players seen: {st['other']}")
    if st["welcome"]: print("server greeting:", st["welcome"][:100])
    print("LOGIN OK" if st["frames"] else "NO DATA FROM SERVER")


if __name__ == "__main__":
    main()
