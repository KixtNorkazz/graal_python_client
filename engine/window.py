"""Minimal SDL2 window via ctypes (no pygame/tkinter needed): present RGBA frames, deliver key/text events."""
import ctypes, ctypes.util

_sdl = None
SDL_INIT_VIDEO, SDL_WINDOWPOS_CENTERED = 0x20, 0x2FFF0000
SDL_WINDOW_SHOWN, SDL_WINDOW_RESIZABLE = 0x4, 0x20
SDL_PIXELFORMAT_ABGR8888 = 0x16762004
SDL_QUIT, SDL_KEYDOWN, SDL_KEYUP, SDL_TEXTINPUT = 0x100, 0x300, 0x301, 0x303
SDL_WINDOWEVENT, SDL_WINDOWEVENT_CLOSE = 0x200, 14
SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN, SDL_MOUSEBUTTONUP, SDL_MOUSEWHEEL = 0x400, 0x401, 0x402, 0x403

K_RETURN, K_ESCAPE, K_BACKSPACE, K_F12 = 13, 27, 8, 0x40000045
K_TAB, K_F11 = 9, 0x40000044
KMOD_SHIFT, KMOD_CTRL = 0x3, 0xC0
K_RIGHT, K_LEFT, K_DOWN, K_UP = 0x4000004F, 0x40000050, 0x40000051, 0x40000052
K_DELETE, K_HOME, K_END, K_PAGEUP, K_PAGEDOWN = 127, 0x4000004A, 0x4000004D, 0x4000004B, 0x4000004E
REPEATING = {K_RIGHT, K_LEFT, K_DOWN, K_UP, K_BACKSPACE, K_DELETE, K_PAGEUP, K_PAGEDOWN}

def load_sdl():
    """The SDL2 library: Linux libSDL2-2.0.so.0, Windows SDL2.dll (system folders, PATH, or next to this file), macOS libSDL2-2.0.0.dylib."""
    import os, sys
    here = os.path.dirname(os.path.abspath(__file__))
    if sys.platform == "win32" and hasattr(os, "add_dll_directory"): os.add_dll_directory(here)
    names = [os.path.join(here, "SDL2.dll") if sys.platform == "win32" else None, ctypes.util.find_library("SDL2-2.0"), ctypes.util.find_library("SDL2"), "libSDL2-2.0.so.0", "SDL2.dll", os.path.join(here, "SDL2.dll"), "libSDL2-2.0.0.dylib"]
    err = None
    for n in names:
        if not n: continue
        try: return ctypes.CDLL(n)
        except OSError as e: err = e
    raise OSError("SDL2 not found (Linux: libsdl2-2.0-0, Windows: put SDL2.dll next to the client or on PATH): %s" % err)

class Window:
    """An SDL window. Several can exist at once (the game and, say, the player list): every window yields only its own events."""
    _all = {}

    def __init__(self, title, w, h, scale=1, secondary=False):
        global _sdl
        import collections
        self.mod = 0; self.secondary = secondary; self.queue = collections.deque()
        _sdl = load_sdl()
        L = _sdl
        L.SDL_CreateWindow.restype = ctypes.c_void_p
        L.SDL_CreateWindow.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint32]
        L.SDL_CreateRenderer.restype = ctypes.c_void_p
        L.SDL_CreateRenderer.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32]
        L.SDL_CreateTexture.restype = ctypes.c_void_p
        L.SDL_CreateTexture.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        L.SDL_UpdateTexture.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        L.SDL_RenderCopy.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        L.SDL_RenderClear.argtypes = [ctypes.c_void_p]; L.SDL_RenderPresent.argtypes = [ctypes.c_void_p]
        L.SDL_PollEvent.argtypes = [ctypes.c_void_p]; L.SDL_SetWindowTitle.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        L.SDL_GetError.restype = ctypes.c_char_p
        L.SDL_GetWindowSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        L.SDL_GetWindowPosition.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
        L.SDL_SetWindowPosition.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        L.SDL_GetWindowID.argtypes = [ctypes.c_void_p]; L.SDL_GetWindowID.restype = ctypes.c_uint32
        L.SDL_SetWindowFullscreen.argtypes = [ctypes.c_void_p, ctypes.c_uint32]   # without it a 64-bit window pointer is passed as a 32-bit int (F11 crashed on Windows)
        L.SDL_DestroyWindow.argtypes = [ctypes.c_void_p]; L.SDL_DestroyRenderer.argtypes = [ctypes.c_void_p]; L.SDL_DestroyTexture.argtypes = [ctypes.c_void_p]
        if L.SDL_Init(SDL_INIT_VIDEO) != 0: raise RuntimeError("SDL_Init: " + L.SDL_GetError().decode())
        self.w, self.h = w, h
        self.win = L.SDL_CreateWindow(title.encode(), SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, int(w * scale), int(h * scale),
                                      SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE)
        if not self.win: raise RuntimeError("SDL_CreateWindow: " + L.SDL_GetError().decode())
        self.ren = L.SDL_CreateRenderer(self.win, -1, 0) or L.SDL_CreateRenderer(self.win, -1, 1)
        self.tex = L.SDL_CreateTexture(self.ren, SDL_PIXELFORMAT_ABGR8888, 1, w, h)
        self.id = L.SDL_GetWindowID(self.win); Window._all[self.id] = self
        L.SDL_StartTextInput()
        self._ev = ctypes.create_string_buffer(64)

    def present(self, rgba: bytes):
        L = _sdl; L.SDL_UpdateTexture(self.tex, None, rgba, self.w * 4)
        L.SDL_RenderClear(self.ren); L.SDL_RenderCopy(self.ren, self.tex, None, None); L.SDL_RenderPresent(self.ren)

    def toggle_fullscreen(self):
        self.full = not getattr(self, "full", False)
        _sdl.SDL_SetWindowFullscreen(self.win, 0x1001 if self.full else 0)

    def title(self, t): _sdl.SDL_SetWindowTitle(self.win, t.encode("latin1", "replace"))

    def place_beside(self, other):
        """Move this window next to `other` (to its right), so both are visible at once."""
        x, y, w, h = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        _sdl.SDL_GetWindowPosition(other.win, ctypes.byref(x), ctypes.byref(y)); _sdl.SDL_GetWindowSize(other.win, ctypes.byref(w), ctypes.byref(h))
        _sdl.SDL_SetWindowPosition(self.win, x.value + w.value + 8, y.value)

    def _size(self):
        ww, wh = ctypes.c_int(), ctypes.c_int(); _sdl.SDL_GetWindowSize(self.win, ctypes.byref(ww), ctypes.byref(wh)); return max(1, ww.value), max(1, wh.value)

    def _parse(self, ev):
        """One SDL event as (window id, event tuple) with the coordinates in the logical size of that window, or None."""
        raw = ev.raw; t = int.from_bytes(raw[0:4], "little")
        wid = int.from_bytes(raw[8:12], "little"); target = Window._all.get(wid) or self
        if t == SDL_QUIT: return None, ("quit",)
        if t == SDL_WINDOWEVENT: return (wid, ("quit",)) if raw[12] == SDL_WINDOWEVENT_CLOSE else None
        if t in (SDL_KEYDOWN, SDL_KEYUP):
            sym = int.from_bytes(raw[20:24], "little"); target.mod = int.from_bytes(raw[24:26], "little")
            if raw[13]: return (target.id, ("repeat", sym)) if t == SDL_KEYDOWN else None
            return target.id, ("down" if t == SDL_KEYDOWN else "up", sym)
        if t in (SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN, SDL_MOUSEBUTTONUP):
            mx = int.from_bytes(raw[20:24], "little", signed=True); my = int.from_bytes(raw[24:28], "little", signed=True)
            ww, wh = target._size(); lx, ly = mx * target.w // ww, my * target.h // wh
            return (target.id, ("mousemove", lx, ly) if t == SDL_MOUSEMOTION else ("mousedown" if t == SDL_MOUSEBUTTONDOWN else "mouseup", raw[16], lx, ly))
        if t == SDL_MOUSEWHEEL:
            dy = int.from_bytes(raw[20:24], "little", signed=True)
            if int.from_bytes(raw[24:28], "little") == 1: dy = -dy
            return target.id, ("wheel", dy)
        if t == SDL_TEXTINPUT: return target.id, ("text", raw[12:44].split(b"\0")[0].decode("utf-8", "replace"))
        return None

    def events(self):
        """Yield ('quit',), ('down', keysym), ('repeat', keysym) while a key is held, ('up', keysym), ('text', str), ('mousemove', x, y), ('mousedown'|'mouseup', button, x, y), ('wheel', dy).
        Events of another window are kept for that window; closing a window gives it a 'quit'."""
        while _sdl.SDL_PollEvent(self._ev):
            got = self._parse(self._ev)
            if got is None: continue
            wid, ev = got
            if wid is None:
                for w in list(Window._all.values()): w.queue.append(ev)
            else: Window._all.get(wid, self).queue.append(ev)
        while self.queue: yield self.queue.popleft()

    def close(self):
        Window._all.pop(self.id, None)
        if self.secondary:
            _sdl.SDL_DestroyTexture(self.tex); _sdl.SDL_DestroyRenderer(self.ren); _sdl.SDL_DestroyWindow(self.win)
        else: _sdl.SDL_Quit()
