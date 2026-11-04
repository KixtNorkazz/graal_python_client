"""Sound: WAV decode (stdlib `wave`) + a small software mixer, played through an SDL2 audio callback (ctypes).
Works without a device: `Mixer.mix(n)` is plain Python and `Audio.played` records every request (used by tests)."""
import array, ctypes, os, sys, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets

RATE, CH = 22050, 2
_cache = {}

def load_wav(name):
    """-> array('h') of interleaved stereo samples at RATE, or None (missing / unsupported format, e.g. ADPCM)."""
    key = os.path.basename(name).lower()
    if key in _cache: return _cache[key]
    out = None; p = assets.find(key)
    if p:
        try:
            with wave.open(p, "rb") as w:
                nch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
                raw = w.readframes(n)
            if width == 1: s = array.array("h", [(b - 128) << 8 for b in raw])
            elif width == 2: s = array.array("h"); s.frombytes(raw[:len(raw) // 2 * 2])
            else: raise wave.Error("unsupported width")
            frames = len(s) // nch; out = array.array("h")
            step = rate / RATE; k = 0.0
            while int(k) < frames:
                i = int(k) * nch
                l = s[i]; r = s[i + 1] if nch > 1 else l
                out.append(l); out.append(r); k += step
        except (wave.Error, EOFError, OSError): out = None
    _cache[key] = out
    return out

def _forget_missing(key=None):
    for k in [k for k, v in _cache.items() if v is None]: del _cache[k]
assets.listeners.append(_forget_missing)

class Mixer:
    def __init__(self): self.voices = []; self.loop = None; self.gain = (1.0, 1.0)   # (sound effects, looped sounds), 0..1 from the settings
    def play(self, samples, loop=False, name=""):
        if loop:
            self.loop = [samples, 0, True, name]
        else:
            if len(self.voices) >= 16: self.voices.pop(0)
            self.voices.append([samples, 0, False, name])
    def stop_loop(self): self.loop = None
    def stop(self, name=None):
        """GS1 stopsound [file]: stop the voices (and the loop) playing that file, or everything."""
        key = name.lower() if name else None
        self.voices = [v for v in self.voices if key and v[3].lower() != key]
        if self.loop and (not key or self.loop[3].lower() == key): self.loop = None
    def mix(self, nframes):
        """-> bytes of nframes stereo s16 samples."""
        acc = [0] * (nframes * CH)
        vs = self.voices + ([self.loop] if self.loop else [])
        for v in vs:
            smp, pos = v[0], v[1]; n = len(smp)
            if not n: continue
            g = self.gain[1] if v[2] else self.gain[0]
            if g <= 0.0:   # muted: only move on, so it does not start over when the volume comes back
                pos += nframes * CH
                v[1] = pos % n if v[2] else min(pos, n); continue
            for j in range(nframes * CH):
                if pos >= n:
                    if v[2]: pos = 0
                    else: break
                acc[j] += smp[pos] if g >= 1.0 else int(smp[pos] * g); pos += 1
            v[1] = pos
        self.voices = [v for v in self.voices if v[1] < len(v[0])]
        return array.array("h", [max(-32768, min(32767, a)) for a in acc]).tobytes()

class Audio:
    def __init__(self, device=True):
        self.mixer = Mixer(); self.played = []; self.dev = None; self._cb = None
        if device: self._open()

    def _open(self):
        try:
            import window; L = window.load_sdl()
            if L.SDL_InitSubSystem(0x10) != 0: return
            class Spec(ctypes.Structure):
                _fields_ = [("freq", ctypes.c_int), ("format", ctypes.c_uint16), ("channels", ctypes.c_uint8), ("silence", ctypes.c_uint8),
                            ("samples", ctypes.c_uint16), ("padding", ctypes.c_uint16), ("size", ctypes.c_uint32),
                            ("callback", ctypes.c_void_p), ("userdata", ctypes.c_void_p)]
            CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_int)
            def cb(_, stream, length):
                try: data = self.mixer.mix(length // (2 * CH))
                except Exception: data = bytes(length)
                ctypes.memmove(stream, data, length)
            self._cb = CB(cb); spec = Spec(RATE, 0x8010, CH, 0, 1024, 0, 0, ctypes.cast(self._cb, ctypes.c_void_p), None)
            L.SDL_OpenAudioDevice.restype = ctypes.c_uint32
            self.dev = L.SDL_OpenAudioDevice(None, 0, ctypes.byref(spec), None, 0)
            if self.dev: L.SDL_PauseAudioDevice(self.dev, 0)
            self._L = L
        except OSError: self.dev = None

    @property
    def active(self): return bool(self.dev)

    def play(self, name, loop=False):
        smp = load_wav(name); self.played.append((name, loop, smp is not None))
        if smp is not None: self.mixer.play(smp, loop, os.path.basename(name))
        return smp is not None

    def set_volumes(self, effects, loops):
        """Volumes from the settings, 0..1 (0 = silent)."""
        self.mixer.gain = (max(0.0, min(1.0, effects)), max(0.0, min(1.0, loops)))

    def stop_loop(self): self.mixer.stop_loop()
    def stop(self, name=None): self.stopped = getattr(self, 'stopped', []) + [name]; self.mixer.stop(name)
