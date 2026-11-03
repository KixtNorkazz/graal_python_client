"""Start the game: the login window, then the game.  python3 start.py [--account NAME] [--scale 2] ...  (start.sh / start.bat do the same)

The code is in engine/ and is not meant to be changed. Your own files are here, next to this one: paths.json (folders), settings.json (F1),
login.json (the remembered account), crash.log, and worlds/<server name>/ with what the client downloaded, sorted into heads/, bodies/,
tilesets/, ganis/, images/ ... You can put your own pictures in those folders too."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import crashguard, viewer

if __name__ == "__main__":
    crashguard.run(viewer.main)
