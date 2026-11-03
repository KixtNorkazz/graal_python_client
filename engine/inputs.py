"""Keyboard / mouse state and events for scripts.

GS1: `keydown(n)` (0 up, 1 left, 2 down, 3 right, 4 A, 5 S, 6 D), `mousex/mousey` (level tiles), `mousescreenx/y` (px),
`leftmousebutton/rightmousebutton/middlemousebutton`, events `mousedown` / `mouseup` (button name in #p(0)).
GS2: `onKeyDown(code, key)`, `onKeyUp(code, key)`, `onKeyPressed(code, key)`, `onMouseDown(button)`, `onMouseUp(button)`, `onMouseMove()`,
with `code` = Windows virtual-key code (letters upper case, digits 0x30.., Tab 9, ` 192, = 187) and `key` = the character; button = "left"/"middle"/"right".
The viewer feeds SDL events in; tests call the same methods."""
VIEW = (640, 456)

_GS_KEYS = {0x4000_0052: 0, 0x4000_0050: 1, 0x4000_0051: 2, 0x4000_004F: 3, ord("a"): 4, ord("s"): 5, ord("d"): 6}
_VK_OEM = {ord("`"): 192, ord("="): 187, ord("-"): 189, ord(","): 188, ord("."): 190, ord("/"): 191, ord(";"): 186, ord("'"): 222, ord("["): 219, ord("]"): 221, ord("\\"): 220}
_VK_SPECIAL = {13: 13, 27: 27, 8: 8, 9: 9, 32: 32, 0x4000_0052: 38, 0x4000_0050: 37, 0x4000_0051: 40, 0x4000_004F: 39}

_VK_F = {0x4000_003A + k: 112 + k for k in range(12)}

def sdl_to_vk(sym):
    """SDL keysym -> Windows virtual-key code; 0 for keys we do not map (they are not sent to scripts)."""
    if sym >= 0x4000_0000: return _VK_SPECIAL.get(sym) or _VK_F.get(sym) or 0
    if ord("a") <= sym <= ord("z"): return sym - 32
    if ord("0") <= sym <= ord("9"): return sym
    return _VK_SPECIAL.get(sym) or _VK_OEM.get(sym) or (sym & 0xFF)

class Input:
    BUTTONS = {1: "left", 2: "middle", 3: "right"}
    def __init__(self, session):
        self.s = session; self.down = set(); self.vk_down = set(); self.sx = self.sy = 0.0; self.buttons = set()

    def is_down(self, n): return int(n) in self.down
    def vk_is_down(self, vk): return int(vk) in self.vk_down
    def button(self, name): return name in self.buttons

    def cam_origin(self):
        """Top-left of the view in the current level's pixel space (same rule as render.render_scene)."""
        s = self.s; f = getattr(s, "focus", None); cx, cy = (s.cell if s.gmap else (0, 0))
        if f: return f[0] - cx * 1024 - VIEW[0] // 2, f[1] - cy * 1024 - VIEW[1] // 2
        return s.pos[0] + 24 - VIEW[0] // 2, s.pos[1] + 24 - VIEW[1] // 2

    def world(self):
        ox, oy = self.cam_origin(); return (ox + self.sx) / 16, (oy + self.sy) / 16

    def _fire(self, event, params=()):
        self.s.runner.broadcast(event, params=list(params)); self.s.npcrt.broadcast(event, params=list(params))

    def key(self, sym, down, char=""):
        n = _GS_KEYS.get(sym)
        if n is not None: (self.down.add if down else self.down.discard)(n)
        vk = sdl_to_vk(sym); ch = char or (chr(sym) if 32 <= sym < 127 else "")
        if not vk: return
        (self.vk_down.add if down else self.vk_down.discard)(vk)
        if down: self._fire("keydown", [float(vk), ch]); self._fire("keypressed", [float(vk), ch])
        else: self._fire("keyup", [float(vk), ch])

    def wheel(self, dy):
        """Mouse wheel (dy > 0 = away from the user): GS2 onMouseWheel(delta)."""
        self._fire("mousewheel", [float(dy)])

    def mouse_move(self, sx, sy):
        self.sx, self.sy = float(sx), float(sy); self._fire("mousemove", [])

    def mouse_button(self, button, down, sx=None, sy=None):
        if sx is not None: self.sx, self.sy = float(sx), float(sy)
        name = self.BUTTONS.get(button, str(button))
        (self.buttons.add if down else self.buttons.discard)(name)
        self._fire("mousedown" if down else "mouseup", [name])
