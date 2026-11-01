"""The message window of `say2` / `message` / level signs: a box with the text; a long text is split into pages that you flip through with the arrow keys
(Down / Right / Enter / Space / A = next page, Up / Left = back; after the last page the box closes; Esc closes at once). A text that fits on one page stays up
for a few seconds, or until you walk on."""
import time
from PIL import Image, ImageDraw, ImageFont

BOX = (40, 300, 560, 124)
LINES, PAD = 6, 12
_font = None

def font():
    global _font
    if _font is None:
        try: _font = ImageFont.load_default(size=12)
        except Exception: _font = ImageFont.load_default()
    return _font

def wrap(text, width, measure):
    """Split `text` (lines separated by \\n) into lines no wider than `width` pixels, breaking at spaces (a longer word is cut)."""
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            cand = (line + " " + word) if line else word
            if measure(cand) <= width: line = cand; continue
            if line: out.append(line)
            while measure(word) > width and len(word) > 1:
                k = len(word)
                while k > 1 and measure(word[:k]) > width: k -= 1
                out.append(word[:k]); word = word[k:]
            line = word
        out.append(line)
    return out

class MessageBox:
    def __init__(self, text, now=None, measure=None):
        self.text = text; self.page = 0; self.born = now if now is not None else time.time(); self.closed = False
        f = font(); measure = measure or (lambda s: f.getlength(s))
        lines = wrap(text, BOX[2] - 2 * PAD, measure)
        while lines and not lines[-1].strip(): lines.pop()
        self.pages = [lines[i:i + LINES] for i in range(0, max(1, len(lines)), LINES)] or [[""]]

    @property
    def multi(self): return len(self.pages) > 1

    def next(self):
        if self.page + 1 < len(self.pages): self.page += 1
        else: self.closed = True

    def prev(self): self.page = max(0, self.page - 1)

    def expired(self, now=None):
        """A one-page text goes away by itself; a multi-page one waits for the reader."""
        return self.closed or (not self.multi and (now if now is not None else time.time()) - self.born > 8.0)

    def key(self, sym):
        """A key press (SDL keysym). Returns True when the box used it (so the game must not act on it)."""
        import window
        if sym == window.K_ESCAPE: self.closed = True; return True
        if not self.multi: return False
        if sym in (window.K_DOWN, window.K_RIGHT, window.K_RETURN, ord(" "), ord("a")): self.next(); return True
        if sym in (window.K_UP, window.K_LEFT): self.prev(); return True
        return True

    def draw(self, view):
        x, y, w, h = BOX; d = ImageDraw.Draw(view, "RGBA"); f = font()
        d.rectangle((x, y, x + w, y + h), fill=(16, 20, 44, 232), outline=(240, 220, 130, 255), width=2)
        for i, ln in enumerate(self.pages[self.page]): d.text((x + PAD, y + 10 + i * 16), ln, font=f, fill=(255, 255, 255, 255))
        if self.multi:
            more = self.page + 1 < len(self.pages)
            d.text((x + w - PAD - 90, y + h - 18), f"{self.page + 1}/{len(self.pages)}  " + ("(Down: more)" if more else "(Down: close)"), font=f, fill=(240, 220, 130, 255))


SIGN_CHARS = ('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' '0123456789!?-.,#>()#####"####\':/~&### <####;\n')
SIGN_SYMBOLS = {(91,): "[A]", (92,): "[B]", (93,): "[X]", (94,): "[Y]", (77,): "^", (78,): "v", (79,): "<", (80,): ">", (74, 75): "[hand]", (71,): "", (72,): "", (73,): "",
                (86, 86): "#", (87, 88): "#4", (67,): "..."}

def decode_sign(data):
    """Server sign bytes (each already minus 32 by the caller or not: pass the raw bytes) -> text with real line breaks."""
    codes = [b - 32 for b in data]; out = []; i = 0
    while i < len(codes):
        for n in (2, 1):
            sym = SIGN_SYMBOLS.get(tuple(codes[i:i + n]))
            if sym is not None and len(codes[i:i + n]) == n: out.append(sym); i += n; break
        else:
            c = codes[i]; out.append(SIGN_CHARS[c] if 0 <= c < len(SIGN_CHARS) else ""); i += 1
    return "".join(out).replace("#K(13)", "")
