"""Library of weapon files (GRAWP001 containers) from the RP server backup, for `addweapon("name")` of the local NPC server."""
import glob, os, re
import config

DIRS = config.dirs("weapon_dirs")
_idx = None

def index():
    """REALNAME (lower case) -> (name, image, full script text)."""
    global _idx
    if _idx is None:
        _idx = {}
        for d in DIRS:
            for p in sorted(glob.glob(d + "/*")):
                try: t = open(p, encoding="latin1").read()
                except OSError: continue
                n = re.search(r"^REALNAME (.*)$", t, re.M); sc = re.search(r"^SCRIPT\n(.*?)^SCRIPTEND", t, re.S | re.M); im = re.search(r"^IMAGE (.*)$", t, re.M)
                if n and sc: _idx.setdefault(n.group(1).strip().lower(), (n.group(1).strip(), im.group(1).strip() if im else "", sc.group(1)))
    return _idx

def find(name):
    """By exact name or without the leading -+#* marks."""
    idx = index(); k = name.lower()
    if k in idx: return idx[k]
    bare = re.sub(r"^[^a-z0-9]+", "", k)
    return next((v for key, v in idx.items() if re.sub(r"^[^a-z0-9]+", "", key) == bare), None)
