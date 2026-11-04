"""Find Graal image/gani files by (case-insensitive) name across the server world and the client folder."""
import os
import config

ROOTS = config.dirs("asset_dirs") + [os.path.join(config.HERE, "builtin")]
EXT = {".png", ".gif", ".gani", ".nw", ".gmap", ".mng", ".txt", ".graal", ".wav"}
_index = None
_all = {}   # name -> every path with that name (the asset folders can hold the same name twice, in other folders or with other capitals)

def index():
    global _index
    if _index is None:
        _index = {}; _all.clear()
        for root in ROOTS:
            for dp, dn, fn in os.walk(root):
                if config.contains(dp + "/", "RC2") or config.contains(dp + "/", ".git"): continue
                for f in fn:
                    if os.path.splitext(f)[1].lower() in EXT:
                        key, p = f.lower(), os.path.join(dp, f)
                        _all.setdefault(key, []).append(p)
                        old = _index.get(key)
                        if old is None or (old.startswith(root) and p.startswith(root) and p.count(os.sep) < old.count(os.sep)):
                            _index[key] = p
    return _index

fetcher = None
listeners = []

def add_root(folder):
    """Index one more folder (the download cache). Files already known keep their place."""
    for dp, dn, fn in os.walk(folder):
        for f in fn:
            if os.path.splitext(f)[1].lower() in EXT:
                p = os.path.join(dp, f); index().setdefault(f.lower(), p); _all.setdefault(f.lower(), []).append(p)

def candidates(name):
    """Every local copy of a file, the one find() gives first."""
    key = os.path.basename(name).lower(); first = index().get(key)
    return ([first] if first else []) + [p for p in _all.get(key, []) if p != first]

_broken_asked = set()

def broken(name, kind=None):
    """No local copy of the file can be read: ask the server for it once per session (its copy may be damaged too)."""
    key = os.path.basename(name).lower()
    if fetcher is not None and key not in _broken_asked: _broken_asked.add(key); fetcher.want(key, False, kind)

def arrived(key, path):
    index()[key] = path
    if path not in _all.setdefault(key, []): _all[key].insert(0, path)
    for fn in listeners: fn(key)

def find(name: str, level=False, kind=None):
    """The local path of a file; a missing one is asked for from the server (a level file only when `level` says it is really needed).
    `kind` (heads, bodies, hats, swords, shields, tilesets, ...) says which folder of the world a download goes to; see filefetch.kind_of."""
    key = os.path.basename(name).lower(); p = index().get(key)
    if fetcher is not None:
        if p is None: fetcher.want(key, level, kind)
        else: fetcher.revalidate(p)
    return p
