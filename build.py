"""Start Build, the offline level editor.  python3 build.py [level.nw]  (build.sh / build.bat do the same). Levels are saved in levels/."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))
import editor

if __name__ == "__main__":
    editor.main()
