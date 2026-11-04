"""The help texts in the windows: keyboard words on a PC, touch words on a phone (the Android app sets TOUCH = True at start).

Keeping them here lets the PC client and the Android app use the very same window modules."""
TOUCH = False

_TEXTS = {   # key: (PC, touch)
    "inv_status": ("Weapon: {w}  (D uses it, Q = inventory)", "Weapon: {w}  (D uses it)"),
    "inv_none": ("Q: inventory", ""),
    "inv_help": ("Enter = choose   D = use weapon   Q = close", "tap = choose   D = use weapon   Back = close"),
    "pl_button": ("F7 = player list", "Menu > Players"),
    "pl_help": ("(click = choose, double-click or Enter = PM, Esc = close)", "(tap = choose, tap twice = PM, Back = close)"),
    "map_none": ("There is no map for this level.   M = close", "There is no map for this level.   Back = close"),
    "map_close": ("M / Esc = close", "Back = close"),
    "look_help": ("Tab = heads / bodies   Esc = cancel", "type to search   Back = cancel"),
    "settings_help": ("Up/Down choose   Left/Right change   F1 or Esc close", "Tap - / +   Back closes"),
    "bar_chat": ("   Enter = chat", ""),
    "guild_help": ("Left/Right guild   Up/Down member   Enter = wear tag   G / Esc close", "tap a member, then a button   Back closes"),
}


def t(key, **values):
    """The text for `key` on this device, with {placeholders} filled in."""
    return _TEXTS[key][1 if TOUCH else 0].format(**values)
