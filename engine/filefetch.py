"""Fetch missing graphics (images, ganis, sounds) and gmaps from the game server while playing, instead of needing a copy of the server's folders.
A level file (.nw) is fetched only on request, for the links and signs of the level you are in and for the map; scripts and other text files are never fetched.

`assets.find(name)` calls `Fetcher.want(name)` for a file it cannot find locally; the request (PLI_WANTFILE) goes out from `tick()`, a few at a time, and the
answer is stored in the world folder (`worlds/<server name>/<kind>/`, paths.json key `worlds_dir`; see kind_of) with the server's modification time. Only files that something actually asks
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
FETCH_EXT = {".png", ".gif", ".mng", ".jpg", ".jpeg", ".bmp", ".gani", ".wav", ".mp3", ".ogg", ".mid", ".midi", ".gmap"}
FETCH_NAMES = {"heads.txt", "bodies.txt"}
MAX_FILE = 8 << 20   # the largest real game file is a few MB; a server must not fill the phone's storage
KINDS = ("heads", "bodies", "hats", "swords", "shields", "tilesets", "ganis", "sounds", "levels", "images")
SOUND_EXT = {".wav", ".mp3", ".ogg", ".mid", ".midi"}


def kind_of(key, hint=None):
    """The folder of the world a downloaded file goes to: what the caller said it is (a head, a tileset ...), else what its name says.
    heads.txt / bodies.txt (the Appearance lists) stay at the top of the world folder."""
    ext = os.path.splitext(key)[1].lower()
    if key in FETCH_NAMES: return ""
    if ext == ".gani": return "ganis"
    if ext in SOUND_EXT: return "sounds"
    if ext in (".nw", ".gmap"): return "levels"
    return hint if hint in KINDS else "images"


def world_folder_name(name):
    """A folder name for the world, from the server's name (characters Windows does not allow in names are replaced)."""
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name or "").strip().rstrip(". ")
    return s or "server"


BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

class Fetcher:
    def __init__(self, session, folder, clock=time.time):
        self.s, self.folder, self.clock = session, folder, clock
        self.queue, self.out, self.failed, self.checked, self.big = [], {}, {}, set(), {}
        self.received, self.missing, self.stale = [], [], []
        self.asked = set()   # names we requested or asked to revalidate: the only files a server may store here
        self.kinds = {}      # name -> folder of the world it is stored in (heads, tilesets, ...)
        os.makedirs(folder, exist_ok=True); assets.add_root(folder)

    def want(self, name, level=False, kind=None):
        """A file is needed and not known locally. A level file (.nw) is only fetched when `level` is set. `kind`: see kind_of."""
        key = os.path.basename(name).lower()
        if kind and key not in self.kinds: self.kinds[key] = kind
        if not key or BAD.search(key) or (os.path.splitext(key)[1] not in FETCH_EXT and key not in FETCH_NAMES and not (level and key.endswith(".nw"))): return
        if key in self.out or key in self.queue: return
        if self.clock() - self.failed.get(key, -1e9) < RETRY: return
        self.queue.append(key)

    def revalidate(self, path):
        """A cached file was used: ask once per session whether the server has a newer one."""
        key = os.path.basename(path).lower()
        if key in self.checked or not os.path.abspath(path).startswith(os.path.abspath(self.folder) + os.sep): return
        self.checked.add(key); self.asked.add(key)
        try: mt = int(os.stat(path).st_mtime)
        except OSError: return
        self.s.send(gline(34, gint_enc5(mt) + os.path.basename(path).encode("latin1", "replace")))
        self.stale.append(key)

    def tick(self):
        now = self.clock()
        for key, t in list(self.out.items()):
            if now - t > TIMEOUT and key not in self.big: del self.out[key]; self.failed[key] = now; self.missing.append(key)
        while self.queue and len(self.out) < MAX_OUT:
            key = self.queue.pop(0); self.out[key] = now; self.asked.add(key)
            self.s.send(gline(23, key.encode("latin1", "replace")))

    def on_file(self, data):
        """PLO_FILE payload (the raw block without its id byte and trailing newline)."""
        if len(data) < 7: return
        mt = gint(data[:5]); n = data[5] - 0x20
        name = data[6:6 + n].decode("latin1"); body = data[6 + n:]
        key = os.path.basename(name).lower()
        if key in self.big:
            b = self.big[key]
            if len(b["data"]) + len(body) > MAX_FILE: self.big.pop(key); self.out.pop(key, None); self.failed[key] = self.clock(); return
            b["data"] += body; b["mt"] = mt; self.out[key] = self.clock(); return
        self._store(key, name, body, mt)

    def on_large_start(self, name):
        key = os.path.basename(name).lower()
        if key in self.asked: self.big[key] = {"data": b"", "mt": 0}; self.out[key] = self.clock()
    def on_large_end(self, name):
        key = os.path.basename(name).lower(); b = self.big.pop(key, None)
        if b: self._store(key, name, b["data"], b["mt"])

    def on_failed(self, name):
        key = os.path.basename(name).lower(); self.out.pop(key, None); self.failed[key] = self.clock(); self.missing.append(key)

    def on_uptodate(self, name): self.out.pop(os.path.basename(name).lower(), None)

    def _store(self, key, name, body, mt):
        self.out.pop(key, None)
        if BAD.search(key) or key in ("", ".", "..") or key not in self.asked: return
        if len(body) > MAX_FILE: self.failed[key] = self.clock(); return
        old = assets.index().get(key)   # a newer copy of a file we already had stays where it is (in the folder you may have put it)
        if old and os.path.abspath(old).startswith(os.path.abspath(self.folder) + os.sep): path = old
        else:
            sub = os.path.join(self.folder, kind_of(key, self.kinds.get(key))); path = os.path.join(sub, key)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
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
