"""Message window: wrapping, pages, keys, sign decoding."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import window
from messagebox import MessageBox, wrap, decode_sign, SIGN_CHARS

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    m = lambda s: len(s) * 7
    check(wrap("aaa bbb ccc", 50, m) == ["aaa bbb", "ccc"], "wraps at spaces")
    check(wrap("a\\nb".replace("\\n", "\n"), 100, m) == ["a", "b"], "keeps line breaks"); check(max(len(x) for x in wrap("x" * 100, 70, m)) <= 10, "cuts a too long word")
    short = MessageBox("Hello", now=0.0, measure=m); check(not short.multi and not short.expired(5.0) and short.expired(9.0), "a short text: one page, goes away after 8 s")
    check(short.key(window.K_DOWN) is False and short.key(window.K_ESCAPE) and short.closed, "one page: arrows are not used, Esc closes")
    long = MessageBox("\n".join(f"line {i}" for i in range(15)), now=0.0, measure=m); check(len(long.pages) == 3 and long.multi, f"15 lines = 3 pages of 6: {len(long.pages)}")
    check(not long.expired(100.0), "a book waits for the reader")
    check(long.key(window.K_DOWN) and long.page == 1 and long.key(window.K_RIGHT) and long.page == 2, "Down, Right: next page")
    check(long.key(window.K_UP) and long.page == 1 and long.key(window.K_LEFT) and long.page == 0 and long.key(window.K_UP) and long.page == 0, "Up, Left: back (not before the first)")
    long.key(window.K_DOWN); long.key(window.K_DOWN); check(not long.closed, "on the last page"); long.key(window.K_DOWN); check(long.closed and long.expired(), "next after the last page closes it")
    check(MessageBox("x" * 50 + " " + "y" * 50, measure=m).pages[0][0].startswith("x"), "text lands on page 1")
    enc = lambda s: bytes(SIGN_CHARS.index(c) + 32 for c in s)
    check(decode_sign(enc("Hello, World!\n")) == "Hello, World!\n", "sign code: letters, punctuation, newline")
    check(decode_sign(bytes([91 + 32]) + enc(" go")) == "[A] go", "sign code: the A button symbol")
    from PIL import Image
    v = Image.new("RGBA", (640, 456)); long.closed = False; long.draw(v); check(v.getbbox() is not None, "draws")
    print("messagebox tests passed")

if __name__ == "__main__": main()
