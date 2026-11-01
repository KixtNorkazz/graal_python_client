"""Minimal SDL2 window via ctypes (no pygame/tkinter needed): present RGBA frames, deliver key/text events."""
import ctypes, ctypes.util

_sdl = None
SDL_INIT_VIDEO, SDL_WINDOWPOS_CENTERED = 0x20, 0x2FFF0000
SDL_WINDOW_SHOWN, SDL_WINDOW_RESIZABLE = 0x4, 0x20
SDL_PIXELFORMAT_ABGR8888 = 0x16762004
SDL_QUIT, SDL_KEYDOWN, SDL_KEYUP, SDL_TEXTINPUT = 0x100, 0x300, 0x301, 0x303
SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN, SDL_MOUSEBUTTONUP, SDL_MOUSEWHEEL = 0x400, 0x401, 0x402, 0x403

K_RETURN, K_ESCAPE, K_BACKSPACE, K_F12 = 13, 27, 8, 0x40000045
K_TAB, K_F11 = 9, 0x40000044
K_RIGHT, K_LEFT, K_DOWN, K_UP = 0x4000004F, 0x40000050, 0x40000051, 0x40000052

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
    def __init__(self, title, w, h, scale=1):
        global _sdl
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
        if L.SDL_Init(SDL_INIT_VIDEO) != 0: raise RuntimeError("SDL_Init: " + L.SDL_GetError().decode())
        self.w, self.h = w, h
        self.win = L.SDL_CreateWindow(title.encode(), SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, int(w * scale), int(h * scale),
                                      SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE)
        if not self.win: raise RuntimeError("SDL_CreateWindow: " + L.SDL_GetError().decode())
        self.ren = L.SDL_CreateRenderer(self.win, -1, 0) or L.SDL_CreateRenderer(self.win, -1, 1)
        self.tex = L.SDL_CreateTexture(self.ren, SDL_PIXELFORMAT_ABGR8888, 1, w, h)
        L.SDL_StartTextInput()
        self._ev = ctypes.create_string_buffer(64)

    def present(self, rgba: bytes):
        L = _sdl; L.SDL_UpdateTexture(self.tex, None, rgba, self.w * 4)
        L.SDL_RenderClear(self.ren); L.SDL_RenderCopy(self.ren, self.tex, None, None); L.SDL_RenderPresent(self.ren)

    def toggle_fullscreen(self):
        self.full = not getattr(self, "full", False)
        _sdl.SDL_SetWindowFullscreen(self.win, 0x1001 if self.full else 0)

    def title(self, t): _sdl.SDL_SetWindowTitle(self.win, t.encode("latin1", "replace"))

    def events(self):
        """Yield ('quit',), ('down', keysym), ('up', keysym), ('text', str), ('mousemove', x, y), ('mousedown'|'mouseup', button, x, y), ('wheel', dy)."""
        while _sdl.SDL_PollEvent(self._ev):
            t = int.from_bytes(self._ev.raw[0:4], "little")
            if t == SDL_QUIT: yield ("quit",)
            elif t in (SDL_KEYDOWN, SDL_KEYUP):
                repeat = self._ev.raw[13]; sym = int.from_bytes(self._ev.raw[20:24], "little")
                if not repeat: yield ("down" if t == SDL_KEYDOWN else "up", sym)
            elif t in (SDL_MOUSEMOTION, SDL_MOUSEBUTTONDOWN, SDL_MOUSEBUTTONUP):
                mx = int.from_bytes(self._ev.raw[20:24], "little", signed=True); my = int.from_bytes(self._ev.raw[24:28], "little", signed=True)
                ww, wh = ctypes.c_int(), ctypes.c_int(); _sdl.SDL_GetWindowSize(self.win, ctypes.byref(ww), ctypes.byref(wh))
                lx, ly = mx * self.w / max(1, ww.value), my * self.h / max(1, wh.value)
                if t == SDL_MOUSEMOTION: yield ("mousemove", lx, ly)
                else: yield ("mousedown" if t == SDL_MOUSEBUTTONDOWN else "mouseup", self._ev.raw[16], lx, ly)
            elif t == SDL_MOUSEWHEEL:
                dy = int.from_bytes(self._ev.raw[20:24], "little", signed=True)
                if self._ev.raw[24:28] and int.from_bytes(self._ev.raw[24:28], "little") == 1: dy = -dy
                yield ("wheel", dy)
            elif t == SDL_TEXTINPUT: yield ("text", self._ev.raw[12:44].split(b"\0")[0].decode("utf-8", "replace"))

    def close(self): _sdl.SDL_Quit()
