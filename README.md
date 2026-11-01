# graal_reborn client

A Python client for the Graal online game protocol (versions 2.22 / 2.31), reverse engineered from the original client. It logs in through a list server, renders levels and gmaps with an SDL2 window (loaded with ctypes) and Pillow, and runs GS1 and GS2 scripts for weapons and NPCs on the client side. It is tested against gs2emu.

## Requirements
- Python 3.10 or newer
- `pip install -r requirements.txt` (Pillow)
- SDL2 (`SDL2.dll` is included for Windows, `libSDL2` from your package manager on Linux/macOS)

## Start
```
./start.sh              # Linux/macOS: login screen
start.bat               # Windows: login screen
./start.sh ACCOUNT      # skips the screen, asks for the password in the terminal
python3 viewer.py --account ACCOUNT --listserver host:port
```
After Start the client asks the list server for its game servers and shows them as a list (name, players, language) like the original client; choose one with Up/Down and Enter (or click it and press Join). With `ACCOUNT` on the command line the first server of the list is used. The password can also be given in the environment variable `GRAAL_PASSWORD`. `./debug.sh` / `debug.bat` check Python, Pillow, SDL2, files and the connection to the list server and write `debug.log`.

## Configuration
Which list server the client asks is set in `paths.json` (key `listserver`). Copy `paths.example.json` to `paths.json` next to `viewer.py` and edit it; relative paths in it are relative to that file. `--listserver host:port` on the command line overrides it, and `GRAAL_PATHS` can point at another file. Without a `paths.json` the default `91.99.73.49:9111` (Graal Reborn) is used. To test against your own server, set `"listserver": "127.0.0.1:9111"` (or its address).

| key | meaning |
| --- | --- |
| `listserver` | `host:port` of the list server |
| `cache_dir` | where files downloaded from the game server are stored (default `cache/`) |
| `asset_dirs` | local folders searched for images, ganis, levels and sounds (optional) |
| `class_dirs` | class files used by `join X;` (optional) |
| `server_script_dirs` | server script folders, searched last (optional) |
| `weapon_dirs` | weapon files for the local NPC server (optional) |
| `account_dir` | account folder (only used by live test scripts) |

All the local folders are optional: the client downloads the files it needs from the game server while you play.

## Files from the original client
It's recommended to have the original pics1.png and sprites.png and put them in builtin/

## Controls
Arrow keys walk (diagonals work), `A` grab, `A` + arrow pull/push, `S` sword, `D` fire the active weapon, `Q` inventory, `Tab` chat (Up arrow shows the history), `F11` fullscreen, `F12` screenshot.

## Tests
```
python3 run_tests.py --quick
```
Some tests need level and script data in the folders from `paths.json` and are skipped or fail without it. `ARCHITECTURE.md` describes how the modules fit together.
