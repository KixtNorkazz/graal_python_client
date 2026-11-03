"""Find Graal image/gani files by (case-insensitive) name across the server world and the client folder."""
import os
import config

ROOTS = config.dirs("asset_dirs") + [os.path.join(config.HERE, "builtin")]
EXT = {".png", ".gif", ".gani", ".nw", ".gmap", ".mng", ".txt", ".graal", ".wav"}
_index = None

def index():
    global _index
    if _index is None:
        _index = {}
        for root in ROOTS:
            for dp, dn, fn in os.walk(root):
                if config.contains(dp + "/", "RC2") or config.contains(dp + "/", ".git"): continue
                for f in fn:
                    if os.path.splitext(f)[1].lower() in EXT:
                        key, p = f.lower(), os.path.join(dp, f)
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
            if os.path.splitext(f)[1].lower() in EXT: index().setdefault(f.lower(), os.path.join(dp, f))

def arrived(key, path):
    index()[key] = path
    for fn in listeners: fn(key)

def find(name: str, level=False, kind=None):
    """The local path of a file; a missing one is asked for from the server (a level file only when `level` says it is really needed).
    `kind` (heads, bodies, hats, swords, shields, tilesets, ...) says which folder of the world a download goes to; see filefetch.kind_of."""
    key = os.path.basename(name).lower(); p = index().get(key)
    if fetcher is not None:
        if p is None: fetcher.want(key, level, kind)
        else: fetcher.revalidate(p)
    return p
