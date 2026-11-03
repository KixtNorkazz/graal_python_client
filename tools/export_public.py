"""python3 tools/export_public.py TARGET_FOLDER : copy the committed files of this project into TARGET_FOLDER (your public repository), ready for `git add .` and `git commit`.

Only what is committed on the current branch is copied (the files come from `git archive`), so nothing local (paths.json, logs, caches, accounts) can get in.
The original client's own files (engine/builtin/pics1.png, engine/builtin/sprites.png, engine/logos-1.jpg) are left out and ignored by the copy's .gitignore. Files of the project overwrite the ones in TARGET_FOLDER. Nothing is deleted: files that are in TARGET_FOLDER's repository but no longer in the project (a LICENSE you
added, or a file that was removed or renamed here) are only listed, so you decide. Before it finishes the copy is searched for names and paths that must not be
published, and the script stops with an error if it finds any."""
import io, os, re, shutil, subprocess, sys, tarfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the project folder (this script is in tools/)
FORBIDDEN = re.compile("|".join(["Ki" + "xt", "Nork" + "azz", "/ho" + "me/", "proton" + "mail", "val_" + "backup", "old" + "val", "Valik" + "orlia", "ZzT" + "est"]), re.I)
KEEP_OUT = ("engine/builtin/pics1.png", "engine/builtin/sprites.png", "engine/logos-1.jpg")
IGNORE_LINES = ("engine/builtin/pics1.png", "engine/builtin/sprites.png", "engine/logos-1.jpg")
TEXT = {".py", ".md", ".txt", ".json", ".sh", ".bat", ".gani", ".nw"}


def main():
    if len(sys.argv) != 2: print(__doc__); return 1
    target = os.path.abspath(sys.argv[1])
    if os.path.isdir(target) and os.listdir(target) and not os.path.isdir(os.path.join(target, ".git")):
        print("%s is not empty and is not a git repository; use an empty folder or a repository." % target); return 1
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=HERE, capture_output=True, check=True).stdout
    os.makedirs(target, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = [m for m in tar.getmembers() if m.name not in KEEP_OUT]; names = {m.name for m in members if m.isfile()}; tar.extractall(target, members=members, filter="data")
    gi = os.path.join(target, ".gitignore")
    with open(gi, encoding="utf-8") as f: have = f.read().split("\n")
    with open(gi, "a", encoding="utf-8", newline="\n") as f: f.write("".join(l + "\n" for l in IGNORE_LINES if l not in have))
    bad = []
    for name in sorted(names):
        if os.path.splitext(name)[1].lower() in TEXT:
            with open(os.path.join(target, name), encoding="latin1") as fh:
                for i, ln in enumerate(fh, 1):
                    if FORBIDDEN.search(ln): bad.append("%s:%d: %s" % (name, i, ln.strip()[:100]))
    if bad: print("NOT clean:\n" + "\n".join(bad[:20])); return 2
    extra = []
    if os.path.isdir(os.path.join(target, ".git")):
        tracked = subprocess.run(["git", "ls-files"], cwd=target, capture_output=True, text=True).stdout.split("\n")
        extra = [t for t in tracked if t and t not in names]
    print("%d files copied to %s, no forbidden names found." % (len(names), target))
    if extra: print("In your repository but not in the project (kept, delete them yourself if they are old): " + ", ".join(extra))
    print("Now: cd there, git add ., git commit, git push."); return 0


if __name__ == "__main__":
    sys.exit(main())
