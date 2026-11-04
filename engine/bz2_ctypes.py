"""bzip2 decompression through the libbz2 shared library (ctypes), for Python builds without the _bz2 module (python-for-android)."""
import ctypes

BZ_OK, BZ_OUTBUFF_FULL = 0, -8
_lib = None


def _load():
    global _lib
    if _lib is None:
        for name in ("libbz2.so", "libbz2.so.1", "libbz2.so.1.0"):
            try: _lib = ctypes.CDLL(name); break
            except OSError: continue
        else: raise ImportError("libbz2 not found")
        f = _lib.BZ2_bzBuffToBuffDecompress
        f.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint), ctypes.c_char_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int]
        f.restype = ctypes.c_int
    return _lib


class BZ2Decompressor:
    """Enough of bz2.BZ2Decompressor for one complete compressed frame: decompress(data, max_length) and eof."""
    def __init__(self): self.eof = False; _load()

    def decompress(self, data, max_length=-1):
        limit = max_length if max_length and max_length > 0 else 1 << 30
        size = min(limit, max(4096, len(data) * 8))
        while True:
            out = ctypes.create_string_buffer(size); n = ctypes.c_uint(size)
            r = _lib.BZ2_bzBuffToBuffDecompress(out, ctypes.byref(n), bytes(data), len(data), 0, 0)
            if r == BZ_OK: self.eof = True; return out.raw[:n.value]
            if r == BZ_OUTBUFF_FULL and size < limit: size = min(limit, size * 4); continue
            if r == BZ_OUTBUFF_FULL: return out.raw[:n.value]
            raise ValueError("bzip2 data is damaged (code %d)" % r)
