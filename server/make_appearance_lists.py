"""python3 make_appearance_lists.py WORLD_FOLDER : write heads.txt and bodies.txt (one image name per line) into the server's world folder.

The client's appearance window (F) reads these two files from the server. A game server does not tell a player which heads and bodies it has, so run this
on the server (again when heads or bodies are added; a cron job does it). WORLD_FOLDER is the folder with `heads/` and `bodies/` (and `global/heads`, `global/bodies`)."""
import os, sys

EXT = (".png", ".gif", ".mng", ".jpg")


def names(world, kind):
    seen = {}
    for sub in (kind, os.path.join("global", kind)):
        folder = os.path.join(world, sub)
        if os.path.isdir(folder):
            for n in sorted(os.listdir(folder)):
                if os.path.splitext(n)[1].lower() in EXT: seen.setdefault(n.lower(), n)
    return sorted(seen.values(), key=str.lower)


def main():
    if len(sys.argv) != 2 or not os.path.isdir(sys.argv[1]): print(__doc__); return 1
    world = sys.argv[1]
    for kind in ("heads", "bodies"):
        found = names(world, kind); tmp = os.path.join(world, kind + ".txt.part")
        with open(tmp, "w", encoding="latin1", errors="replace", newline="\n") as f: f.write("\n".join(found) + "\n")
        os.replace(tmp, os.path.join(world, kind + ".txt")); print("%s.txt: %d names" % (kind, len(found)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
