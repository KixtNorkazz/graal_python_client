"""Fetch missing files (images, ganis, sounds, gmaps ...) from the game server while playing, instead of needing a copy of the server's folders.

`assets.find(name)` calls `Fetcher.want(name)` for a file it cannot find locally; the request (PLI_WANTFILE) goes out from `tick()`, a few at a time, and the
answer is stored in the cache folder (`cache/<server>/`, paths.json key `cache_dir`) with the server's modification time. Only files that something actually asks
for are fetched, so levels the player never enters cost nothing. A file that is already in the cache is checked once per session (PLI_UPDATEFILE with its
modification time; the server only resends it if it differs).

Server answers: PLO_FILE (102, raw: {GINT5 modtime}{gchar len}{name}{data}); files over 32000 bytes come as PLO_LARGEFILESTART (68) {name}, PLO_LARGEFILESIZE (84),
several PLO_FILE chunks and PLO_LARGEFILEEND (69). PLO_FILESENDFAILED (30) {name} = the server does not have it, PLO_FILEUPTODATE (45) {name}."""
import os, re, time
import assets
from graalproto import gline, gchar, gint

MAX_OUT = 6
TIMEOUT = 12.0
RETRY = 180.0
BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

class Fetcher:
    def __init__(self, session, folder, clock=time.time):
        self.s, self.folder, self.clock = session, folder, clock
        self.queue, self.out, self.failed, self.checked, self.big = [], {}, {}, set(), {}
        self.received, self.missing, self.stale = [], [], []
        os.makedirs(folder, exist_ok=True); assets.add_root(folder)

    def want(self, name):
        """A file is needed and not known locally."""
        key = os.path.basename(name).lower()
        if not key or BAD.search(key) or os.path.splitext(key)[1] not in assets.EXT: return
        if key in self.out or key in self.queue: return
        if self.clock() - self.failed.get(key, -1e9) < RETRY: return
        self.queue.append(key)

    def revalidate(self, path):
        """A cached file was used: ask once per session whether the server has a newer one."""
        key = os.path.basename(path).lower()
        if key in self.checked or os.path.dirname(os.path.abspath(path)) != os.path.abspath(self.folder): return
        self.checked.add(key)
        try: mt = int(os.stat(path).st_mtime)
        except OSError: return
        self.s.send(gline(34, gint_enc5(mt) + os.path.basename(path).encode("latin1", "replace")))
        self.stale.append(key)

    def tick(self):
        now = self.clock()
        for key, t in list(self.out.items()):
            if now - t > TIMEOUT and key not in self.big: del self.out[key]; self.failed[key] = now; self.missing.append(key)
        while self.queue and len(self.out) < MAX_OUT:
            key = self.queue.pop(0); self.out[key] = now
            self.s.send(gline(23, key.encode("latin1", "replace")))

    def on_file(self, data):
        """PLO_FILE payload (the raw block without its id byte and trailing newline)."""
        if len(data) < 7: return
        mt = gint(data[:5]); n = data[5] - 0x20
        name = data[6:6 + n].decode("latin1"); body = data[6 + n:]
        key = os.path.basename(name).lower()
        if key in self.big: self.big[key]["data"] += body; self.big[key]["mt"] = mt; self.out[key] = self.clock(); return
        self._store(key, name, body, mt)

    def on_large_start(self, name): key = os.path.basename(name).lower(); self.big[key] = {"data": b"", "mt": 0}; self.out[key] = self.clock()
    def on_large_end(self, name):
        key = os.path.basename(name).lower(); b = self.big.pop(key, None)
        if b: self._store(key, name, b["data"], b["mt"])

    def on_failed(self, name):
        key = os.path.basename(name).lower(); self.out.pop(key, None); self.failed[key] = self.clock(); self.missing.append(key)

    def on_uptodate(self, name): self.out.pop(os.path.basename(name).lower(), None)

    def _store(self, key, name, body, mt):
        self.out.pop(key, None)
        if BAD.search(key) or not key: return
        path = os.path.join(self.folder, key)
        try:
            with open(path + ".part", "wb") as f: f.write(body)
            os.replace(path + ".part", path)
            if mt: os.utime(path, (mt, mt))
        except OSError: self.failed[key] = self.clock(); return
        self.received.append(key); assets.arrived(key, path)
        if key.endswith(".nw") and key == (getattr(self.s, "level_name", None) or "").lower():
            try: self.s.ensure_neighbours()
            except Exception: pass
        if key.endswith(".gmap") and key == (getattr(self.s, "gmap", None) or "").lower():
            try: self.s.ensure_neighbours()
            except Exception: pass

def gint_enc5(v):
    from graalproto import gint_enc
    return gint_enc(v, 5)
