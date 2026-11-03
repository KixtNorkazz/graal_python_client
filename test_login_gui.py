"""python3 test_login_gui.py : the login screen's logic (fields, Tab / Enter / Backspace, masked password, button hit test, saved nickname + account)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import login_gui as lg, window

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    lg.SAVED = os.path.join(tempfile.mkdtemp(), "login.json"); os.environ.pop("GRAAL_PASSWORD", None)
    s = lg.Screen(lg.load_saved())
    check(s.focus == "nick" and s.vals == {"nick": "", "account": "", "password": ""}, "empty start: the nickname field has the focus")
    for ch in "Nisse": s.typed(ch)
    check(s.key(lg.K_TAB) is None and s.focus == "account", "Tab moves to Account")
    s.typed("TestA"); s.key(window.K_BACKSPACE); check(s.vals["account"] == "Test", "Backspace deletes")
    s.typed("A"); check(s.key(window.K_RETURN) is None and s.focus == "password", "Enter in a field moves on")
    s.typed("hemmelig"); check(s.vals["password"] == "hemmelig", "password typed")
    check(s.key(window.K_RETURN) == "start", "Enter in the password field presses Start")
    check(s.key(window.K_ESCAPE) == "quit", "Esc quits")
    im = s.draw(0.0); check(im.size == (lg.W, lg.H), f"frame size {im.size}")
    bx, by, bw, bh = lg.BTN; check(s.hit(bx + 5, by + 5) == "start" and s.hit(bx - 3, by) is None, "the Start button hit test")
    bx, by, bw, bh = lg.BUILD_BTN; check(s.hit(bx + 5, by + 5) == "build", "the Build button hit test")
    fx, fy, fw, fh = s.field_rect("account"); check(s.hit(fx + 3, fy + 3) == "account", "click on a field")
    s.busy = True; s.typed("x"); check(s.vals["password"] == "hemmelig" and s.key(window.K_RETURN) is None, "nothing is typed or sent while logging in")
    lg.save_saved(s.vals); d = lg.load_saved()
    check(d == {"nick": "Nisse", "account": "TestA"} and "password" not in open(lg.SAVED).read(), f"nickname and account are remembered, the password never: {d}")
    s2 = lg.Screen(d); check(s2.focus == "password", "with nickname and account known the password field has the focus")
    import minclient
    g = lambda t: bytes([32 + len(t)]) + t.encode()
    L = minclient.parse_server_entry(bytes([33, 40]) + b"".join(g(t) for t in ("H Alpha Server", "English", "Some text", "http://x.example", "Beta", "3", "192.0.2.7", "9093")))
    check(len(L) == 1 and L[0]["name"] == "Alpha Server" and L[0]["host"] == "192.0.2.7" and L[0]["port"] == 9093 and L[0]["players"] == "3", f"server list entry parsed: {L}")
    s3 = lg.Screen({}); s3.servers = L + [dict(L[0], name="Beta Server")]
    im = s3.draw(0.0); check(im.size == (lg.W, lg.H), "the server list draws")
    check(s3.hit(*s3.row_rect(1)[:2]) == "row1" and s3.key(window.K_DOWN) is None and s3.sel == 1 and s3.key(window.K_DOWN) is None and s3.sel == 0, "Up/Down choose a server, click hit test")
    check(s3.key(window.K_RETURN) == "join" and s3.key(window.K_ESCAPE) is None and s3.servers is None, "Enter joins, Esc goes back to the fields")
    print("login gui tests passed")

main()
