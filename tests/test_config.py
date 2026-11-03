"""python3 test_config.py : paths.json handling (relative paths, ~, Windows drive letters, GRAAL_PATHS, missing file)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import config

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    d = tempfile.mkdtemp(); p = os.path.join(d, "p.json")
    json.dump({"asset_dirs": ["lv", "~/x", "C:\\Graal\\world"], "class_dirs": "cls", "account_dir": "acc"}, open(p, "w"))
    os.environ["GRAAL_PATHS"] = p; c = config.load()
    check(c["asset_dirs"][0] == os.path.normpath(os.path.join(d, "lv")), f"relative to the json file: {c['asset_dirs']}")
    check(c["asset_dirs"][1] == os.path.normpath(os.path.expanduser("~/x")), "~ expanded")
    check(c["asset_dirs"][2] == os.path.normpath("C:\\Graal\\world"), f"a drive letter path is kept: {c['asset_dirs'][2]}")
    check(c["class_dirs"] == [os.path.normpath(os.path.join(d, "cls"))] and c["account_dir"] == os.path.normpath(os.path.join(d, "acc")), "a single string is a one-item list")
    check(c["weapon_dirs"] == [] and c["server_script_dirs"] == [], "keys that are not given are empty")
    os.environ["GRAAL_PATHS"] = os.path.join(d, "missing.json"); c = config.load()
    check(all(c[k] == [] for k in ("asset_dirs", "class_dirs")) and c["account_dir"] == "", "a missing file gives empty folders, no crash")
    del os.environ["GRAAL_PATHS"]
    check(config.contains("C:\\a\\local_data\\sub\\f.png", "local_data/sub") and not config.contains("/a/b/c.png", "local_data"), "contains() ignores the separator")
    print("config tests passed")

main()
