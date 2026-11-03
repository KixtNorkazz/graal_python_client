"""Folders the client reads from, kept in `paths.json` in the project folder (one above engine/) (or in the file named by the environment variable GRAAL_PATHS).

paths.json keys (lists or single strings; `~` and relative paths are allowed, relative to the folder of paths.json; use `/` or `\\` - both work on Windows):
  asset_dirs          where images, ganis, levels and sounds are looked for (first match wins): the server's world folder, this project, the level backup
  class_dirs          class files for `join X;`, searched first (the backups' script folders)
  server_script_dirs  the running server's own classes, searched last (after the project's own `classes/` folder)
  weapon_dirs         weapon files (GRAWP001 containers) for `addweapon("name")` of the local NPC server
  account_dir         the server's `accounts` folder (only the live test scripts read it)
  listserver          the list server to log in at, "host:port" (viewer.py --listserver overrides it)
  worlds_dir          where files fetched from the game server are stored (default `worlds/` next to paths.json): one folder per server, named
                      after it, sorted into heads/ bodies/ hats/ swords/ shields/ tilesets/ ganis/ sounds/ levels/ images/ (your own files there are used too)
Folders that do not exist are skipped."""
import json, os

HERE = ENGINE = os.path.dirname(os.path.abspath(__file__))   # engine/: the code and its own files (builtin/, classes/)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project folder: paths.json, login.json, worlds/ ... (this file is in engine/)
DEFAULTS = {"asset_dirs": [], "class_dirs": [], "server_script_dirs": [], "weapon_dirs": [], "account_dir": "", "worlds_dir": "worlds", "listserver": "91.99.73.49:9111"}

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
    path = os.environ.get("GRAAL_PATHS") or os.path.join(ROOT, "paths.json")
    cfg = dict(DEFAULTS)
    try: raw = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError): raw = {}
    base = os.path.dirname(os.path.abspath(path))
    for k in DEFAULTS:
        if k in raw: cfg[k] = raw[k]
    for k in ("asset_dirs", "class_dirs", "server_script_dirs", "weapon_dirs"): cfg[k] = _norm(cfg[k], base)
    acc = _norm(cfg["account_dir"], base); cfg["account_dir"] = acc[0] if acc else ""
    wd = _norm(cfg["worlds_dir"], base); cfg["worlds_dir"] = wd[0] if wd else os.path.join(base, "worlds")
    return cfg

CFG = load()
def dirs(key): return CFG[key]
def contains(path, part):
    """Does `path` lie inside a folder called `part` (a path fragment with `/`)? Separator-independent, for Windows."""
    return ("/" + part.strip("/") + "/") in path.replace("\\", "/")
