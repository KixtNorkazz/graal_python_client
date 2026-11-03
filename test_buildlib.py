"""python3 test_buildlib.py : the Build library (saved tile objects, NPC templates) and the cursor of the editor's text fields."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import os, tempfile
import buildlib, editor_forms, window
from editor_forms import Field, Form
from leveldoc import Pattern

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    folder = tempfile.mkdtemp(); lib = buildlib.Library(folder)
    check(lib.objects == [] and lib.npc_names() == [] and lib.npc("none") is None, "an empty library")
    i = lib.add_object(Pattern(2, 2, [1, 2, 3, 4]), "four"); lib.add_object(Pattern.single(9))
    check(i == 0 and lib.objects[1]["name"] == "object 2" and lib.pattern(0).tiles == [1, 2, 3, 4], "objects are added and read back as patterns")
    check(buildlib.Library(folder).objects == lib.objects, "objects are still there in a new session")
    lib.remove_object(0); check(len(buildlib.Library(folder).objects) == 1, "an object can be removed")
    with open(os.path.join(folder, "objects.json"), "w") as f: f.write('[{"w": 2, "h": 2, "tiles": [1]}, {"w": 1, "h": 1, "tiles": [5]}, 7]')
    check(len(buildlib.Library(folder).objects) == 1, "damaged entries are skipped")
    with open(os.path.join(folder, "objects.json"), "w") as f: f.write("not json")
    check(buildlib.Library(folder).objects == [], "a damaged file gives an empty library")

    check(lib.save_npc("Door 1", "door.png", "if (created) {\n  setshape 1,32,32;\n}") and lib.npc_names() == ["Door 1"], "an NPC template is saved as a text file")
    check(lib.npc("Door 1") == ("door.png", "if (created) {\n  setshape 1,32,32;\n}"), "image and script read back")
    lib.save_npc("plain", "-", "x"); check(open(os.path.join(folder, "npcs", "plain.txt")).read() == "x\n" and lib.npc("plain") == ("-", "x"), "a template without image is only the script")
    check(not lib.save_npc("../..", "-", "x") and lib.npc_names() == ["Door 1", "plain"], "a name that is nothing but path characters is refused")
    check(lib.save_npc("../evil", "-", "x") and os.path.exists(os.path.join(folder, "npcs", "evil.txt")) and not os.path.exists(os.path.join(folder, "evil.txt")), "path characters in a name cannot leave the npcs folder")
    check(lib.remove_npc("plain") and lib.npc_names() == ["Door 1", "evil"], "a template can be removed")

    fl = Field("a", "A:", "hello\nworld", lines=3); f = Form("t", [fl]); key = lambda k, m=0: f.handle(("down", k), m)
    key(window.K_LEFT); key(window.K_LEFT); f.handle(("text", "X")); check(fl.value == "hello\nworXld" and fl.pos == 10, "text goes in at the cursor")
    key(window.K_UP); check(fl.pos == 4, "Up goes to the line above, same column"); key(editor_forms.K_HOME); f.handle(("text", "<")); check(fl.value == "<hello\nworXld", "Home")
    key(editor_forms.K_END); key(editor_forms.K_DELETE); check(fl.value == "<helloworXld", "End and Delete (joins the lines)")
    key(window.K_BACKSPACE); check(fl.value == "<hellworXld", "Backspace deletes before the cursor")
    fl.value = "abc"; check(fl.pos == 3, "setting the value puts the cursor at the end")
    key(window.K_RETURN, window.KMOD_CTRL); check(f.handle(("down", window.K_RETURN), window.KMOD_CTRL)[0] == "ok", "Ctrl+Enter accepts")
    lib2 = buildlib.Library(tempfile.mkdtemp()); check(lib2.setting("tileset") == "", "no setting yet")
    lib2.set_setting("tileset", "x.png"); lib2.set_setting("other", "y"); check(buildlib.Library(lib2.folder).setting("tileset") == "x.png" and buildlib.Library(lib2.folder).setting("other") == "y", "settings are kept between sessions")
    with open(lib2._settings_path(), "w") as fh: fh.write("[1, 2")
    check(lib2.setting("tileset", "d") == "d", "a broken settings file is ignored"); lib2.set_setting("tileset", "z.png"); check(lib2.setting("tileset") == "z.png", "and replaced on the next save")
    print("buildlib tests passed")

main()
