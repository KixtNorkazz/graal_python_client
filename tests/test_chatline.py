import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from chatline import History
def check(c, m):
    if not c: raise AssertionError(m)
def main():
    p = os.path.join(tempfile.mkdtemp(), "h.txt"); h = History(p, limit=3)
    check(h.up("x") == "x", "no history: nothing changes")
    for l in ("one", "two", "three", "four", "four", "  "): h.push(l)
    check(h.lines == ["two", "three", "four"], f"last 3, no duplicates, no blanks: {h.lines}")
    check(h.up("draft") == "four" and h.up("") == "three" and h.up("") == "two" and h.up("") == "two", "Up walks back and stops at the oldest")
    check(h.down("") == "three" and h.down("") == "four" and h.down("") == "draft", "Down walks forward and returns to what was typed")
    check(History(p, limit=3).lines == ["two", "three", "four"], "kept between runs")
    print("chatline tests passed")
if __name__ == "__main__": main()
