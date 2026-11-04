"""Graal 2.x wire protocol (as used by Graal_222.exe / Graal_231.exe), recovered by reverse engineering.

Frame:   u16be length | [u8 type, only after login] | body        (length counts type byte + body)
Types:   2 = raw, 4 = zlib, 6 = bzip2;  login phase (first client packet) = zlib, no type byte, no XOR.
XOR:     k = (k * 0x8088405 + seed) & 0xFFFFFFFF per 32-bit LE word; k0 = 0x04A80B38.
         type 2: first min(ceil(n/4), 12) words; type 4/6: first min(n//4, 4) words. Applied to the *wire* body.
         Each direction has its own key state that persists across packets; both use the client's seed.
Lines:   body is '\\n'-separated lines: chr(id + 0x20) + payload. Numbers/strings use chr(n + 0x20) length prefixes.
"""
import struct, zlib
try:
    import bz2
    BZ2Decompressor = bz2.BZ2Decompressor
except ImportError:   # python-for-android has no _bz2: libbz2 through ctypes (the server sends packets over 4 KB as bzip2)
    bz2 = None
    from bz2_ctypes import BZ2Decompressor

K0, MULT, M32 = 0x04A80B38, 0x8088405, 0xFFFFFFFF
T_RAW, T_ZLIB, T_BZ2 = 2, 4, 6


def gchar(n): return bytes([n + 0x20])
def gstr(s: bytes): return gchar(len(s)) + s
def gline(pid: int, payload: bytes = b""): return gchar(pid) + payload + b"\n"


def xor_words(data, key, seed, limit):
    d = bytearray(data)
    n = min((len(d) + 3) >> 2, limit) if limit == 12 else min(len(d) >> 2, limit)
    for w in range(n):
        key = (key * MULT + seed) & M32
        if len(d) < w * 4 + 4:
            kb = struct.pack("<I", key)
            for j in range(len(d) - w * 4): d[w * 4 + j] ^= kb[j]
        else:
            struct.pack_into("<I", d, w * 4, struct.unpack_from("<I", d, w * 4)[0] ^ key)
    return bytes(d), key


class Stream:
    """One direction of a connection. Use `encode` for what you send, `feed` for what you receive."""
    def __init__(self, seed: int, login_phase: bool = False):
        self.seed, self.key, self.login, self.buf = seed & 0x7F, K0, login_phase, b""

    def encode(self, plain: bytes, ptype=None) -> bytes:
        if self.login:
            body = zlib.compress(plain, 9)
            return struct.pack(">H", len(body)) + body
        ptype = ptype or (T_RAW if len(plain) < 0x30 else T_ZLIB if len(plain) < 0x1000 or bz2 is None else T_BZ2)
        body = plain if ptype == T_RAW else zlib.compress(plain, 9) if ptype == T_ZLIB else bz2.compress(plain, 9)
        body, self.key = xor_words(body, self.key, self.seed, 12 if ptype == T_RAW else 4)
        return struct.pack(">H", len(body) + 1) + bytes([ptype]) + body

    def feed(self, data: bytes):
        """Yield (type, plaintext) for each complete frame in the stream."""
        self.buf += data
        while len(self.buf) >= 2:
            n = (self.buf[0] << 8) | self.buf[1]
            if len(self.buf) < n + 2: return
            pk, self.buf = self.buf[2:2 + n], self.buf[2 + n:]
            if self.login:
                yield 3, _inflate(zlib.decompressobj(), pk); continue
            t, body = pk[0], pk[1:]
            body, self.key = xor_words(body, self.key, self.seed, 12 if t == T_RAW else 4)
            yield t, (_inflate(zlib.decompressobj(), body) if t == T_ZLIB else _inflate(BZ2Decompressor(), body) if t == T_BZ2 else body)


MAX_INFLATED = 32 << 20

def _inflate(d, data):
    out = d.decompress(data, MAX_INFLATED)
    if not d.eof: raise ValueError('compressed frame is incomplete or expands past the limit')
    return out


def listserver_hello(seed: int, version=b"GNW30123newmain"):
    return gline(7, gchar(seed) + version)
def listserver_login(account: bytes, password: bytes):
    return gline(1, gstr(account) + gstr(password))
def game_login(seed: int, version: bytes, account: bytes, password: bytes):
    return gline(5, gchar(seed) + version + gstr(account) + gstr(password))
def language(lang: bytes = b"English"): return gline(37, lang)


def split_lines(plain: bytes):
    """Split a decoded body into (packet_id, payload). Binary packets (e.g. file data) may not split cleanly."""
    return [(ln[0] - 0x20, ln[1:]) for ln in plain.split(b"\n") if ln]


def gint(bs: bytes) -> int:
    """Graal multi-byte int: each byte is (value + 0x20), 7 bits per byte, most significant first."""
    v = 0
    for b in bs: v = (v << 7) | ((b - 0x20) & 0x7F)
    return v

def gint_enc(v: int, n: int) -> bytes:
    return bytes(((v >> (7 * (n - 1 - i))) & 0x7F) + 0x20 for i in range(n))

PLO_RAWDATA = 100

class LineParser:
    """Splits decoded frames into ('line', id, payload) and ('raw', id, data) items; keeps raw-mode state.
    A packet can be split over two frames (gs2emu does that over a slow link): the unfinished end of a frame is kept and joined
    to the next one. Taking it as a whole packet cut NPC props short (no y, then no script), so a level lost its tiledefs."""
    def __init__(self): self.raw = 0; self.rest = b""
    def feed(self, plain: bytes):
        if self.rest: plain, self.rest = self.rest + plain, b""
        pos = 0
        while pos < len(plain):
            if self.raw > 0:
                if len(plain) - pos < self.raw: self.rest = plain[pos:]; return   # the raw block goes on in the next frame
                chunk, pos, self.raw = plain[pos:pos + self.raw], pos + self.raw, 0
                yield ("raw", chunk[0] - 0x20, chunk[1:-1] if chunk.endswith(b"\n") else chunk[1:])
                continue
            nl = plain.find(b"\n", pos)
            if nl < 0: self.rest = plain[pos:]; return   # no newline yet: the packet goes on in the next frame
            line, pos = plain[pos:nl], nl + 1
            if not line: continue
            pid, payload = line[0] - 0x20, line[1:]
            yield ("line", pid, payload)
            if pid == PLO_RAWDATA and len(payload) == 3: self.raw = gint(payload)


def prop_x2(v: bytes) -> int:
    x = gint(v); return -(x >> 1) if x & 1 else x >> 1

def enc_pos(px: int) -> bytes:
    return gint_enc((abs(px) << 1) | (1 if px < 0 else 0), 2)

PROP_GANI, PROP_SPRITE, PROP_X2, PROP_Y2 = 10, 17, 78, 79
DIRS = {"U": 0, "L": 1, "D": 2, "R": 3}

def initial_props(nick=b"unknown", head=b"val-saurvoldpriesthead.gif", lang=b"English"):
    """The props line both real clients send once the level data has arrived (captured)."""
    return gline(2, gchar(0) + gstr(nick) + gchar(11) + gchar(len(head) + 100) + head
                 + gchar(13) + bytes([0x22, 0x20, 0x2a, 0x24, 0x32]) + gchar(18) + gchar(20)
                 + gchar(31) + b"   " + gchar(33) + gchar(0) + gchar(52) + gstr(lang)
                 + gchar(75) + gstr(b"wind") + gchar(76) + gint_enc(1252, 3))

def walk_lines(direction: str, steps: int, x: int, y: int, stride=8):
    """One id-2 line per 50 ms tick, like the real client: first tick carries gani+sprite(direction), rest only the axis."""
    d = DIRS[direction]
    for k in range(1, steps + 1):
        if direction in "LR": x += -stride if direction == "L" else stride; prop, v = PROP_X2, x
        else: y += -stride if direction == "U" else stride; prop, v = PROP_Y2, y
        head = gchar(PROP_GANI) + gstr(b"walk") + gchar(PROP_SPRITE) + gchar(d) if k == 1 else b""
        yield gline(2, head + gchar(prop) + enc_pos(v)), x, y

def idle_line(): return gline(2, gchar(PROP_GANI) + gstr(b"idle"))
