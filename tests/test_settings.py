"""python3 test_settings.py : the settings window (F1) changes and saves the volumes, the mixer follows them, and a looped sound from a level
NPC stops when the player leaves the level or gmap (the waves of portwolfe followed the player onto the worldmap); a weapon's loop goes on."""
import os, sys, tempfile, array
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
import settings, audio, gclient, window

def check(c, m):
    if not c: raise AssertionError(m)

def main():
    with tempfile.TemporaryDirectory() as d:
        settings.PATH = os.path.join(d, "settings.json")
        v = settings.load(); check(v == settings.DEFAULTS, f"defaults without a file: {v}")
        s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "a", "b", "222", ("127.0.0.1", 1)); s.send = lambda l: None
        s.audio = audio.Audio(device=False)
        w = settings.SettingsWindow(v); w.toggle(s)
        w.cursor = 2; w.key(window.K_LEFT, s); w.key(window.K_LEFT, s)
        check(w.values["loop_volume"] == settings.DEFAULTS["loop_volume"] - 2 * settings.STEP and s.audio.mixer.gain[1] == w.values["loop_volume"] / 100, f"Left lowers the loop volume: {w.values} {s.audio.mixer.gain}")
        check(settings.load()["loop_volume"] == w.values["loop_volume"], "and it is saved")
        w.cursor = 0; w.key(window.K_RETURN, s); check(s.audio.mixer.gain == (0.0, 0.0) and settings.load()["sound"] is False, f"Sound off mutes everything: {s.audio.mixer.gain}")
        minus, plus = w._buttons(1); w.click(plus[0] + 2, plus[1] + 2, s); check(w.values["effects_volume"] == min(100, settings.DEFAULTS["effects_volume"] + settings.STEP), "the + button")
        open(settings.PATH, "w").write("{broken"); check(settings.load() == settings.DEFAULTS, "a damaged file gives the defaults")
        # The frame rate cap: Left/Right step through the choices, the last one is no cap; it is saved and gives the frame time.
        w.cursor = 3; check(settings.ROWS[3][0] == "fps_cap" and w.values["fps_cap"] == 40 and abs(settings.frame_time(w.values) - 0.025) < 1e-9, "default cap 40 fps (25 ms, as before)")
        w.key(window.K_RIGHT, s); check(w.values["fps_cap"] == 60 and settings.load()["fps_cap"] == 60, "Right raises it to 60 and it is saved")
        for _ in range(9): w.key(window.K_RIGHT, s)
        check(w.values["fps_cap"] == 0 and settings.frame_time(w.values) == 0.0 and w._value_text("fps_cap") == "Off", "the last choice is no cap")
        for _ in range(20): w.key(window.K_LEFT, s)
        check(w.values["fps_cap"] == 20 and w._value_text("fps_cap") == "20 fps", "Left stops at 20")
        open(settings.PATH, "w").write('{"fps_cap": 33}'); check(settings.load()["fps_cap"] == 40, "a value that is not a choice gives the default")
        check(settings.load({"sound": False, "fps_cap": 20})["fps_cap"] == 20 and "fps_cap" in settings.load({"sound": False}), "the phone's own defaults (with or without fps_cap)")
        # Any on/off value is a toggle row (the Android app adds "Battery saver" this way).
        rows0, d0 = settings.ROWS, dict(settings.DEFAULTS)
        try:
            settings.DEFAULTS["zz_switch"] = False; settings.ROWS = rows0 + (("zz_switch", "Zz switch"),)
            w2 = settings.SettingsWindow(settings.load()); w2.toggle(s); w2.cursor = len(settings.ROWS) - 1
            check(w2._value_text("zz_switch") == "Off", "an added on/off row starts Off")
            w2.key(window.K_RETURN, s); check(w2.values["zz_switch"] is True and settings.load()["zz_switch"] is True and w2._value_text("zz_switch") == "On", "Enter turns it on and it is saved")
            w2.key(window.K_LEFT, s); check(w2.values["zz_switch"] is False, "Left / - turns it off again")
        finally: settings.ROWS = rows0; settings.DEFAULTS.clear(); settings.DEFAULTS.update(d0)
        w.key(settings.K_F1, s); check(not w.open, "F1 closes it")
    m = audio.Mixer(); m.play([1000] * 8, False, "fx"); m.play([2000] * 8, True, "waves"); m.gain = (1.0, 0.5)
    out = array.array("h"); out.frombytes(m.mix(2)); check(list(out) == [2000] * 4, f"effects at 100 % plus the loop at 50 %: {list(out)}")
    # A level NPC's looped sound stops when the player changes world; a weapon's does not.
    import tempfile as _t, wave
    with _t.TemporaryDirectory() as d:
        p = os.path.join(d, "zz-waves.wav")
        with wave.open(p, "wb") as wf: wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(22050); wf.writeframes(b"\x10\x00" * 200)
        import assets; orig = assets.find; assets.find = lambda n, level=False, kind=None: p if n.lower().endswith("zz-waves.wav") else orig(n, level)
        try:
            s.gmap = "portwolfe.gmap"; s.play_sound("zz-waves.wav", loop=True); check(s.audio.mixer.loop is not None, "the waves loop")
            s._enter_world("portwolfe.gmap"); check(s.audio.mixer.loop is not None, "walking inside the same gmap keeps them")
            s._enter_world("worldmap.gmap"); check(s.audio.mixer.loop is None, "leaving portwolfe stops them")
            s.gmap = "worldmap.gmap"; s.play_sound("zz-waves.wav", loop=True, from_weapon=True); s._enter_world("selnic.gmap")
            check(s.audio.mixer.loop is not None, "a weapon's loop goes on in the next level")
        finally: assets.find = orig
    print("settings tests passed")

main()
