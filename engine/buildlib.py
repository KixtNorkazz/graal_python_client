"""The Build library: tile objects (a rectangle of tiles saved from a level) and NPC templates, kept between sessions in `build_data/`.

Tile objects are in `objects.json`; an NPC template is a text file `npcs/<name>.txt` holding the NPC script, with an optional first line `//IMAGE name.png`."""
import json, os, re
from leveldoc import Pattern

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FOLDER = os.path.join(os.path.dirname(HERE), "build_data")   # in the project folder
IMAGE_LINE = "//IMAGE "


def safe_name(name):
    """A file-name-safe version of a template name ("" if nothing is left)."""
    return re.sub(r"[^A-Za-z0-9_.\- ]", "", name).strip().strip(".")


class Library:
    def __init__(self, folder=None):
        self.folder = folder or DEFAULT_FOLDER
        self.objects = self._load_objects()

    def _settings_path(self): return os.path.join(self.folder, "settings.json")

    def setting(self, key, default=""):
        try:
            with open(self._settings_path(), encoding="utf-8") as f: v = json.load(f).get(key, default)
        except (OSError, ValueError, AttributeError): return default
        return v if isinstance(v, type(default)) else default

    def set_setting(self, key, value):
        try:
            with open(self._settings_path(), encoding="utf-8") as f: data = json.load(f)
        except (OSError, ValueError): data = {}
        if not isinstance(data, dict): data = {}
        data[key] = value; os.makedirs(self.folder, exist_ok=True)
        with open(self._settings_path(), "w", encoding="utf-8") as f: json.dump(data, f)

    def _objects_path(self): return os.path.join(self.folder, "objects.json")

    def _load_objects(self):
        try:
            with open(self._objects_path(), encoding="utf-8") as f: data = json.load(f)
        except (OSError, ValueError): return []
        return [o for o in data if isinstance(o, dict) and isinstance(o.get("tiles"), list) and o.get("w", 0) * o.get("h", 0) == len(o["tiles"]) > 0]

    def _save_objects(self):
        os.makedirs(self.folder, exist_ok=True)
        with open(self._objects_path(), "w", encoding="utf-8") as f: json.dump(self.objects, f)

    def add_object(self, pattern, name=""):
        self.objects.append(dict(name=name or "object %d" % (len(self.objects) + 1), w=pattern.w, h=pattern.h, tiles=list(pattern.tiles)))
        self._save_objects(); return len(self.objects) - 1

    def remove_object(self, index):
        if 0 <= index < len(self.objects): del self.objects[index]; self._save_objects()

    def pattern(self, index):
        o = self.objects[index]; return Pattern(o["w"], o["h"], o["tiles"])

    def npc_names(self):
        try: return sorted(n[:-4] for n in os.listdir(os.path.join(self.folder, "npcs")) if n.lower().endswith(".txt"))
        except OSError: return []

    def npc(self, name):
        """(image, script) of a template, or None."""
        try:
            with open(os.path.join(self.folder, "npcs", safe_name(name) + ".txt"), encoding="latin1") as f: text = f.read().replace("\r", "")
        except OSError: return None
        image = "-"
        if text.startswith(IMAGE_LINE): first, _, text = text.partition("\n"); image = first[len(IMAGE_LINE):].strip() or "-"
        return image, text.rstrip("\n")

    def save_npc(self, name, image, script):
        name = safe_name(name)
        if not name: return False
        os.makedirs(os.path.join(self.folder, "npcs"), exist_ok=True)
        with open(os.path.join(self.folder, "npcs", name + ".txt"), "w", encoding="latin1", errors="replace", newline="\n") as f:
            f.write((IMAGE_LINE + image + "\n" if image not in ("", "-") else "") + script + "\n")
        return True

    def remove_npc(self, name):
        try: os.remove(os.path.join(self.folder, "npcs", safe_name(name) + ".txt")); return True
        except OSError: return False
