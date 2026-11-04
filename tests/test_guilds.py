"""python3 test_guilds.py : guilds. The server's gr.guild answers are read into Session.guilds, the guild tag counts (#g) only when the server
lists us in that guild, wearing a tag goes through the server's setnick, and the guild window offers the buttons of your rank and asks again
before leave / remove."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine"))
from PIL import Image
import gclient, guilds, window
from graalproto import gint_enc

def check(c, m):
    if not c: raise AssertionError(m)

def action(*fields):
    """A PLO_TRIGGERACTION (48) from the server: from player 0, npc 0, x/y 0, then the CSV."""
    return gint_enc(0, 2) + gint_enc(0, 3) + bytes([0x20, 0x20]) + gclient.csv_join(list(fields)).encode("latin1")

def main():
    s = gclient.Session.__new__(gclient.Session); gclient.Session.__init__(s, "Rowan", "b", "222", ("127.0.0.1", 1)); sent = []; s.send = lambda l: sent.append(bytes(l))
    s.account_name = "Rowan"; s.me["NICKNAME"] = "Sir Patrick (Ashford)"
    check(s.guild == "", "before the server has answered, no tag counts")
    s.handle("pkt", 48, action("clientside", "-Guilds", "info", "2", "Ashford", "2", "3", "Rowan", "2", "", "Ada", "0", "", "Patrick", "1", "Sir Patrick Graham, Knight of", "Iron Guard", "0", "1", "Rowan", "0", ""))
    check([g["name"] for g in s.guilds] == ["Ashford", "Iron Guard"] and s.guilds[0]["rank"] == 2, f"info read: {s.guilds}")
    check(s.guilds[0]["members"] == [("Rowan", 2, ""), ("Patrick", 1, "Sir Patrick Graham, Knight of"), ("Ada", 0, "")], f"members (account, rank, given name) sorted by rank, then name: {s.guilds[0]['members']}")
    check(s.guild == "Ashford", "a tag of a guild we are in counts (#g)")
    s.me["NICKNAME"] = "Sir Patrick (Nobodys)"; check(s.guild == "", "a tag of a guild we are not in does not")
    s.me["NICKNAME"] = "Sir Patrick"; check(s.guild == "" and s.nick_base() == "Sir Patrick", "no tag")
    s.handle("pkt", 48, action("clientside", "-Guilds", "message", "Ada is now a member of Ashford."))
    check(s.guild_message[0] == "Ada is now a member of Ashford.", "server messages are kept")
    s.handle("pkt", 48, action("clientside", "-Guilds", "info", "3", "Broken", "0"))   # cut short: what was read is kept, nothing crashes
    check(s.guilds == [], f"a damaged answer gives no guilds rather than a crash: {s.guilds}")
    s.handle("pkt", 48, action("clientside", "-Guilds", "info", "1", "Ashford", "1", "2", "Rowan", "1", "", "Ada", "0", "Dame Ada"))

    sent.clear(); s.me["NICKNAME"] = "Sir Patrick (Old Guild)"; s.set_guild_tag("Ashford")
    check(sent and b"setnick Sir Patrick (Ashford)" in sent[-1] and sent[-1][0] - 0x20 == 2, f"wearing a tag asks the server with setnick: {sent}")
    sent.clear(); s.set_guild_tag(""); check(b"setnick Sir Patrick\n" in sent[-1], "and without a tag")
    # A guild that gave our account a name: wearing its tag uses that name (the server allows no other with the tag).
    s.guilds[0]["members"][0] = ("Rowan", 1, "Sir Rowan Graham, Knight of"); sent.clear(); s.set_guild_tag("Ashford")
    check(b"setnick Sir Rowan Graham, Knight of (Ashford)" in sent[-1], f"the given name is worn with the tag: {sent[-1]}")
    s.guilds[0]["members"][0] = ("Rowan", 1, "")
    sent.clear(); s.guild_cmd("add", "Ashford", "Bob")
    check(sent[-1][0] - 0x20 == 38 and sent[-1].endswith(b"gr.guild,add,Ashford,Bob\n"), f"commands are gr.guild trigger actions: {sent[-1]}")

    # The window: an officer gets add / remove but not the rank buttons; leave and remove need a second press.
    w = guilds.GuildWindow(); sent.clear(); w.toggle(s); check(w.open and sent[-1].endswith(b"gr.guild,info\n"), "opening asks for a fresh list")
    row1, row2 = w.buttons(s); keys = [k for k, _ in row1 + row2]
    check(keys == ["wear", "untag", "leave", "add", "remove", "name"], f"an officer's buttons: {keys}")
    w.cursor = 1; sent.clear(); w.act("remove", s, now=100.0); check(not sent and "again" in w.status(s, now=100.5), "the first Remove only asks to confirm")
    w.act("remove", s, now=101.0); check(sent and sent[-1].endswith(b"gr.guild,remove,Ashford,Ada\n"), f"the second press within 3 s removes the chosen member: {sent}")
    sent.clear(); w.act("leave", s, now=200.0); w.act("leave", s, now=204.0); check(not sent, "a second press after the time is a new first press")
    w.act("leave", s, now=204.5); check(sent and sent[-1].endswith(b"gr.guild,leave,Ashford\n"), "leave")
    sent.clear(); w.act("add", s); check(w.typing, "Add asks for an account")
    for ch in "Bob": w.typed(ch)
    w.key(window.K_RETURN, s); check(not w.typing and sent[-1].endswith(b"gr.guild,add,Ashford,Bob\n"), "Enter adds")
    w.act("add", s)
    for ch in "Rowanz:Sir Pat (x) Graham, Knight of": w.typed(ch)
    check(w.text == "Rowanz:Sir Pat x Graham, Knight of", f"brackets cannot be typed (the tag is added by the server): {w.text!r}")
    w.text = "Rowanz : Sir Patrick Graham, Knight of"; w.key(window.K_RETURN, s)
    check(sent[-1].endswith(b'gr.guild,add,Ashford,Rowanz,"Sir Patrick Graham, Knight of"\n'), f"Account:Name adds with the name (quoted, it has a comma): {sent[-1]}")
    w.cursor = 1; sent.clear(); w.act("name", s); check(w.typing == "name" and w.text == "Dame Ada", "Name starts from the member's given name")
    for ch in ":x": w.typed(ch)
    check(w.text == "Dame Ada" + "x", f"a name has no ':' in it: {w.text!r}")
    w.text = "Dame Ada of the Hill"; w.key(window.K_RETURN, s); check(sent[-1].endswith(b"gr.guild,nick,Ashford,Ada,Dame Ada of the Hill\n"), f"Enter sets the name: {sent[-1]}")
    w.act("name", s); w.text = ""; w.key(window.K_RETURN, s); check(sent[-1].endswith(b"gr.guild,nick,Ashford,Ada,\n"), "an empty name allows any name again")

    s.guilds[0]["rank"] = 2; keys = [k for k, _ in sum(w.buttons(s), [])]
    check(keys[-3:] == ["officer", "member", "leader"], f"a leader also gets the rank buttons: {keys}")
    w.cursor = 1; sent.clear(); w.act("officer", s); check(sent[-1].endswith(b"gr.guild,rank,Ashford,Ada,officer\n"), "make officer")
    s.guilds[0]["rank"] = 0; keys = [k for k, _ in sum(w.buttons(s), [])]
    check(keys == ["wear", "untag", "leave"], f"a member can only wear the tag and leave: {keys}")
    w.key(window.K_DOWN, s); check(w.cursor == 0, "Down wraps through the members")
    b = w._boxes(s); x0, y0, x1, y1 = b["wear"]; sent.clear(); check(w.click(x0 + 2, y0 + 2, s) and b"setnick" in sent[-1], "clicking Wear tag")
    im = Image.new("RGBA", (640, 480)); w.draw(im, s)
    w.key(guilds.K_G, s); check(not w.open, "G closes it")
    s.guilds = []; w.open = True; w.draw(im, s); w.click(300, 300, s)   # no guilds: draws and clicks without errors
    print("guild tests passed")

main()
