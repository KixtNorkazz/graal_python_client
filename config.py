"""Folders the client reads from, kept in `paths.json` next to this file (or in the file named by the environment variable GRAAL_PATHS).

paths.json keys (lists or single strings; `~` and relative paths are allowed, relative to the folder of paths.json; use `/` or `\\` - both work on Windows):
  asset_dirs          where images, ganis, levels and sounds are looked for (first match wins): the server's world folder, this project, the level backup
  class_dirs          class files for `join X;`, searched first (the backups' script folders)
  server_script_dirs  the running server's own classes, searched last (after the project's own `classes/` folder)
  weapon_dirs         weapon files (GRAWP001 containers) for `addweapon("name")` of the local NPC server
  account_dir         the server's `accounts` folder (only the live test scripts read it)
  listserver          the list server to log in at, "host:port" (viewer.py --listserver overrides it)
  cache_dir           where files fetched from the game server are stored (default `cache/` next to paths.json; one sub-folder per server)
Folders that do not exist are skipped."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {"asset_dirs": [], "class_dirs": [], "server_script_dirs": [], "weapon_dirs": [], "account_dir": "", "cache_dir": "cache", "listserver": "91.99.73.49:9111"}

def _norm(v, base):
    if isinstance(v, str): v = [v] if v else []
    out = []
    for p in v:
        p = str(p)
        if len(p) > 1 and p[1] == ":": out.append(os.path.normpath(p)); continue
        p = os.path.expanduser(p.replace("\\", "/"))
        out.append(os.path.normpath(p if os.path.isabs(p) else os.path.join(base, p)))
    return out

def load():
    path = os.environ.get("GRAAL_PATHS") or os.path.join(HERE, "paths.json")
    cfg = dict(DEFAULTS)
    try: raw = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError): raw = {}
    base = os.path.dirname(os.path.abspath(path))
    for k in DEFAULTS:
        if k in raw: cfg[k] = raw[k]
    for k in ("asset_dirs", "class_dirs", "server_script_dirs", "weapon_dirs"): cfg[k] = _norm(cfg[k], base)
    acc = _norm(cfg["account_dir"], base); cfg["account_dir"] = acc[0] if acc else ""
    cd = _norm(cfg["cache_dir"], base); cfg["cache_dir"] = cd[0] if cd else os.path.join(base, "cache")
    return cfg

CFG = load()
def dirs(key): return CFG[key]
def contains(path, part):
    """Does `path` lie inside a folder called `part` (a path fragment with `/`)? Separator-independent, for Windows."""
    return ("/" + part.strip("/") + "/") in path.replace("\\", "/")
