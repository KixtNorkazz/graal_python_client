"""Fetching missing files from the server: request / answer / large files / failures / timeout / revalidation, and rendering without any local files."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
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
        s0 = len(f.queue); [f.want(n) for n in ("zz-level.nw", "zz-script.txt", "zz-x.graal", "heads.txt")]; assert f.queue[s0:] == ["heads.txt"], f.queue; f.queue.pop(); f.want("zz-level.nw", level=True); assert f.queue[s0:] == ["zz-level.nw"], f.queue; f.queue.pop()
        assets.find("../sub/y.png"); assert f.queue[-1] == "y.png"; f.queue.pop()
        f.tick(); assert s.sent == [b"7zz-nofile.png\n"], s.sent
        seen = []; assets.listeners.append(seen.append)
        f.on_file(pl("zz-nofile.png", b"PNGDATA")); p = assets.find("zz-nofile.png")
        assert p and open(p, "rb").read() == b"PNGDATA" and int(os.stat(p).st_mtime) == 1700000000 and seen == ["zz-nofile.png"]
        assets.find("zz-nofile.png"); assets.find("zz-nofile.png")
        assert s.sent[1:] == [b"B" + gint_enc(1700000000, 5) + b"zz-nofile.png\n"], s.sent
        f.on_uptodate("zz-nofile.png")
        f.on_file(pl("zz-pushed.png", b"X")); f.on_large_start("zz-pushed2.wav"); f.on_file(pl("zz-pushed2.wav", b"X")); f.on_large_end("zz-pushed2.wav")
        assert not os.path.exists(os.path.join(d, "zz-pushed.png")) and not os.path.exists(os.path.join(d, "zz-pushed2.wav")), "a file we never asked for is not stored"
        assets.find("zz-huge.png"); f.queue.remove("zz-huge.png"); f.queue.insert(0, "zz-huge.png"); f.tick()
        f.on_file(pl("zz-huge.png", b"x" * (filefetch.MAX_FILE + 1))); assert not os.path.exists(os.path.join(d, "zz-huge.png")), "a file over MAX_FILE is not stored"
        assets.find("zz-huge2.wav"); f.queue.remove("zz-huge2.wav"); f.queue.insert(0, "zz-huge2.wav"); f.tick(); f.on_large_start("zz-huge2.wav")
        for i in range(9): f.on_file(pl("zz-huge2.wav", b"x" * (1 << 20)))
        f.on_large_end("zz-huge2.wav"); assert not os.path.exists(os.path.join(d, "zz-huge2.wav")) and "zz-huge2.wav" not in f.big, "nor one sent in chunks"
        assets.find("zz-big.wav"); f.queue.remove("zz-big.wav"); f.queue.insert(0, "zz-big.wav"); f.tick()
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
    # worlds/<server name>/<kind>/: a download goes to the folder of what asked for it, or of its file type; a file you put in a sub-folder yourself stays there.
    with tempfile.TemporaryDirectory() as w:
        class S2: level_name = ""; gmap = ""; sent = []
        def _s(line, _l=S2.sent): _l.append(line)
        S2.send = staticmethod(_s)
        f2 = filefetch.Fetcher(S2(), w, clock=lambda: 0.0); old_fetcher = assets.fetcher; assets.fetcher = f2
        try:
            for name, kind in (("zz-h1.png", "heads"), ("zz-b1.png", "bodies"), ("zz-t1.png", "tilesets"), ("zz-x.gani", None), ("zz-s.wav", None), ("zz-w.png", None)):
                assets.find(name, kind=kind)
            f2.tick(); f2.tick()
            for name in ("zz-h1.png", "zz-b1.png", "zz-t1.png", "zz-x.gani", "zz-s.wav", "zz-w.png"): f2.on_file(pl(name, b"DATA"))
            where = {n: os.path.relpath(assets.find(n), w) for n in ("zz-h1.png", "zz-b1.png", "zz-t1.png", "zz-x.gani", "zz-s.wav", "zz-w.png")}
            assert where == {"zz-h1.png": "heads/zz-h1.png", "zz-b1.png": "bodies/zz-b1.png", "zz-t1.png": "tilesets/zz-t1.png", "zz-x.gani": "ganis/zz-x.gani",
                             "zz-s.wav": "sounds/zz-s.wav", "zz-w.png": "images/zz-w.png"}, where
            os.makedirs(os.path.join(w, "heads", "mine")); open(os.path.join(w, "heads", "mine", "zz-own.png"), "wb").write(b"OLD"); assets.add_root(w)
            f2.asked.add("zz-own.png"); f2.on_file(pl("zz-own.png", b"NEW"))
            assert open(os.path.join(w, "heads", "mine", "zz-own.png"), "rb").read() == b"NEW", "a newer copy replaces the file where you put it"
        finally: assets.fetcher = old_fetcher
    assert filefetch.world_folder_name("My Graal Server") == "My Graal Server" and filefetch.world_folder_name('a/b:c*?. ') == "a_b_c__", "folder names"
    print("filefetch tests passed")

if __name__ == "__main__": main()
