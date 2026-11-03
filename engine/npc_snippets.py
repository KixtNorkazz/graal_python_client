"""Starting points for NPC scripts, inserted from the NPC dialog of the level editor (F4)."""

SNIPPETS = (
    ("Say something when touched", "if (playertouchsme) {\n  say2 Hello there!;\n}"),
    ("Warp door", "if (playertouchsme) {\n  setlevel2 other.nw,30,30;\n}"),
    ("Message when a player enters", "if (playerenters) {\n  say2 Welcome!;\n}"),
    ("Repeating timer", "if (created) {\n  timeout = 1;\n}\nif (timeout) {\n  this.count++;\n  timeout = 1;\n}"),
    ("Pay rupees", "if (playertouchsme) {\n  if (playerrupees >= 10) {\n    playerrupees -= 10;\n    say2 Thank you!;\n  } else {\n    say2 You need 10 rupees.;\n  }\n}"),
    ("Blocking object", "if (created) {\n  setshape 1,32,32;\n}"),
    ("GS2: touched", "function onPlayerTouchsMe() {\n  say2(\"Hello there!\");\n}"),
    ("GS2: chat command", "function onPlayerChats() {\n  if (player.chat == \"hello\") {\n    say2(\"Hello \" @ player.nick @ \"!\");\n  }\n}"),
)

QUICK_HEAD, QUICK_BODY = "val-hellsinging-dalmarguard.gif", "hellsinging-dalmarguardbody.gif"
CHARACTER_SCRIPT = (
    "// Character NPC\n"
    "if (created) {\n"
    "  // Initialize the attributes\n"
    "  showcharacter;\n"
    "  setcharprop #3," + QUICK_HEAD + ";\n"
    "  setcharprop #8," + QUICK_BODY + ";\n"
    "  setcharprop #C0,orange;\n"
    "  setcharprop #C1,white;\n"
    "  setcharprop #C2,blue;\n"
    "  setcharprop #C3,red;\n"
    "  setcharprop #C4,black;\n"
    "  setcharprop #2,shield1.gif;\n"
    "  shieldpower = 1;\n"
    "  dir = 2;\n"
    "}"
)
