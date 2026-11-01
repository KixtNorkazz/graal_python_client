"""Fetching missing files from the server: request / answer / large files / failures / timeout / revalidation, and rendering without any local files."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets, filefetch, render, gani
from graalproto import gint_enc, gchar

class Fake:
    def __init__(self): self.sent, self.gmap = [], None
    def send(self, line): self.sent.append(line)

def pl(name, body, mt=1700000000): return gint_enc(mt, 5) + gchar(len(name)) + name.encode() + body

def main():
    d = tempfile.mkdtemp(); clock = [100.0]; s = Fake(); f = filefetch.Fetcher(s, d, clock=lambda: clock[0]); assets.fetcher = f
    try:
        assert assets.find("Zz-nofile.png") is None
        assert f.queue == ["zz-nofile.png"] and not s.sent
        assets.find("zz-nofile.png"); assert len(f.queue) == 1
        assets.find("../evil:x.png"); assert len(f.queue) == 1
        assets.find("../sub/y.png"); assert f.queue[-1] == "y.png"; f.queue.pop()
        f.tick(); assert s.sent == [b"7zz-nofile.png\n"], s.sent
        seen = []; assets.listeners.append(seen.append)
        f.on_file(pl("zz-nofile.png", b"PNGDATA")); p = assets.find("zz-nofile.png")
        assert p and open(p, "rb").read() == b"PNGDATA" and int(os.stat(p).st_mtime) == 1700000000 and seen == ["zz-nofile.png"]
        assets.find("zz-nofile.png"); assets.find("zz-nofile.png")
        assert s.sent[1:] == [b"B" + gint_enc(1700000000, 5) + b"zz-nofile.png\n"], s.sent
        f.on_uptodate("zz-nofile.png")
        f.on_large_start("zz-big.wav"); f.on_file(pl("zz-big.wav", b"AAA")); f.on_file(pl("zz-big.wav", b"BBB")); assert assets.find("zz-big.wav") is None
        f.on_large_end("zz-big.wav"); assert open(assets.find("zz-big.wav"), "rb").read() == b"AAABBB"
        assets.find("zz-gone.gif"); f.tick(); f.on_failed("zz-gone.gif"); assert "zz-gone.gif" in f.missing
        s.sent.clear(); assets.find("zz-gone.gif"); f.tick(); assert not s.sent
        clock[0] += filefetch.RETRY + 1; assets.find("zz-gone.gif"); f.tick(); assert s.sent
        assets.find("zz-quiet.gif"); f.tick(); clock[0] += filefetch.TIMEOUT + 1; f.tick(); assert "zz-quiet.gif" in f.missing
        for i in range(20): assets.find(f"zz-many{i}.gif")
        s.sent.clear(); f.tick(); assert len(f.out) <= filefetch.MAX_OUT
        assert render.read_gmap("zz-nomap.gmap") == []
        assert gani.load("zz-noani") is None
        open(os.path.join(d, "zz-un.gmap"), "w").write("GRMAP001\nWIDTH 2\nHEIGHT 2\nLEVELNAMES\na1.nw,b1.nw\na2.nw,b2.nw\nLEVELNAMESEND\n"); open(os.path.join(d, "zz-q.gmap"), "w").write('GRMAP001\nWIDTH 2\nHEIGHT 1\nLEVELNAMES\n"a1.nw","b1.nw"\nLEVELNAMESEND\n')
        assets.arrived("zz-un.gmap", os.path.join(d, "zz-un.gmap")); assets.arrived("zz-q.gmap", os.path.join(d, "zz-q.gmap"))
        assert render.read_gmap("zz-un.gmap") == [["a1.nw", "b1.nw"], ["a2.nw", "b2.nw"]] and render.read_gmap("zz-q.gmap") == [["a1.nw", "b1.nw"]]
        open(os.path.join(d, "zz-late.gani"), "w").write("SPRITE 0 x.png 0 0 1 1\nANI\n0 0 0\n\n\n\nANIEND\n")
        assets.index()["zz-late.gani"] = os.path.join(d, "zz-late.gani"); assets.arrived("zz-late.gani", os.path.join(d, "zz-late.gani")); assert gani.load("zz-late") is not None
    finally:
        assets.fetcher = None
    print("filefetch tests passed")

if __name__ == "__main__": main()
