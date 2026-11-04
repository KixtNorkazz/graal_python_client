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
python3 start.py --account ACCOUNT --listserver host:port
```
After Start the client asks the list server for its game servers and shows them as a list (name, players, language) like the original client; choose one with Up/Down and Enter (or click it and press Join). With `ACCOUNT` on the command line the first server of the list is used. The password can also be given in the environment variable `GRAAL_PASSWORD`. `./debug.sh` / `debug.bat` check Python, Pillow, SDL2, files and the connection to the list server and write `debug.log`.

## The folder
| | |
| --- | --- |
| `start.py`, `start.sh`, `start.bat` | start the game |
| `build.py`, `build.sh`, `build.bat` | start Build, the level editor |
| `paths.json` | folders and the list server (see below); `paths.example.json` is a template |
| `settings.json` | the settings of the `F1` window (sound, volumes) |
| `login.json`, `crash.log`, `chat_history.txt` | the remembered account (no password), errors, the chat history |
| `worlds/<server name>/` | what the client downloaded from that server, sorted into `heads/ bodies/ hats/ swords/ shields/ tilesets/ ganis/ sounds/ levels/ images/` (pictures that are none of these, like windows and doors, go to `images/`). Files you put in these folders yourself are used too, and a newer download replaces a file where you put it |
| `levels/` | levels made with Build |
| `server/` | files for the game server (the map's player positions, the appearance lists) |
| `engine/` | the code: not meant to be changed |
| `tools/`, `tests/` | developer scripts and the tests |

## Configuration
Which list server the client asks is set in `paths.json` (key `listserver`). Copy `paths.example.json` to `paths.json` (in this folder, next to `start.py`) and edit it; relative paths in it are relative to that file. `--listserver host:port` on the command line overrides it, and `GRAAL_PATHS` can point at another file. Without a `paths.json` the default `91.99.73.49:9111` (Graal Reborn) is used. To test against your own server, set `"listserver": "127.0.0.1:9111"` (or its address).

| key | meaning |
| --- | --- |
| `listserver` | `host:port` of the list server |
| `worlds_dir` | where files downloaded from the game servers are stored (default `worlds/`, one folder per server named after it) |
| `asset_dirs` | local folders searched for images, ganis, levels and sounds (optional) |
| `class_dirs` | class files used by `join X;` (optional) |
| `server_script_dirs` | server script folders, searched last (optional) |
| `weapon_dirs` | weapon files for the local NPC server (optional) |
| `account_dir` | account folder (only used by live test scripts) |

All the local folders are optional: the client downloads the files it needs from the game server while you play.

## Files from the original client
`engine/builtin/pics1.png` (the default tileset) and `engine/builtin/sprites.png` come from the original Graal client; game servers do not have them. Without `pics1.png` levels are drawn without tiles and the status line says `pics1.png missing`. `engine/logos-1.jpg` (optional) is the login screen background.

## Controls
Arrow keys walk (diagonals work), `A` grab, `A` + arrow pull/push, `S` sword, `D` fire the active weapon, `Q` inventory, `Tab` chat (Up arrow shows the history), `M` map with the players on the same gmap, `F` appearance, `F7` player list (click a player to select, double-click or Enter to write a private message; received ones pop up), `F1` settings (sound on/off, volume of sound effects and of looped sounds), `F11` fullscreen, `F12` screenshot.

## Map (M) and player list (F7)
On a server with a `.gmap`, `M` opens the map of the whole gmap: one small picture per level (the level files of the gmap are fetched while it is open), your own position, and the other players who are online on the same gmap with their names. `F7` opens the list of everyone online in a window of its own, placed beside the game window; drag it wherever you like (a second monitor, next to the game) and the game keeps running. Click a player, double-click or Enter to write a private message; Esc or the close button closes it. gs2emu only sends the moves of players close to you, so without help a player more than one cell away is drawn as a ring with a `?` at the position the server last reported. With the server file `server/npcMapPlayers-NPC.txt` in the server's `npcs` folder (gs2emu with an NPC-server reloads it by itself) the map asks the server every 3 seconds for the position of everyone and shows all players on the gmap live. The file is a Control-NPC whose script answers the client's `servermapplayers` trigger action with one private message; the client never shows that message.

## Appearance (F)
`F` opens a window where you choose a head and a body from what the server has, see yourself with them, and press **Done** to wear them (the head and body properties are sent silently, the same as `sethead` and `setbody`, and the server keeps them with the account). Type to filter, arrow keys or the mouse choose, `Tab` switches between heads and bodies, `Esc` cancels. A game server does not list its heads and bodies to players, so run `python3 server/make_appearance_lists.py WORLD_FOLDER` on the server (again when heads or bodies are added); it writes `heads.txt` and `bodies.txt` into the world folder, which the client fetches like any other file. Without those files the client lists the `heads` and `bodies` folders of the local asset folders, and you can type a file name and press Enter.

## Build (level editor)
`./build.sh` (Windows: `build.bat`) or the **Build** button on the login screen opens Build, the level editor for `.nw` levels, modelled on the editor of the original client. It is fully offline (no server or login; levels are uploaded to a server by remote control, which Build does not do). `build.sh level.nw` opens a level; `--dir FOLDER` chooses where levels are opened from and saved to (default: the first folder in `asset_dirs`, otherwise `levels/`).

| | |
| --- | --- |
| `T` tiles | pick tiles in the palette (drag for a rectangle; the palette shows the whole tileset and scrolls sideways with the wheel, the bar under it, the arrow keys or PgUp/PgDn), click or drag to paint; right button drag picks tiles from the level; `K` makes the picked tile the background tile |
| `F` fill | flood fill with the picked tiles |
| `S` select (the tool Build starts with) | drag with the left button to mark a rectangle; drag inside it to move everything in it (the tiles of the current layer and every NPC, chest, sign, baddy and link inside); `Ctrl+C` copies it all, `Ctrl+X` cuts, `Ctrl+V` or `Ctrl+P` and a click pastes, `Delete` clears |
| `O` objects | `N` NPC, `C` chest, `B` baddy: click an empty tile to place, click an object to select and drag it, double-click or `Enter` edits, `Delete` removes. The NPC dialog has a large script field; `F2` picks the image from a list with preview, `F3` loads a script from a file, `F4` inserts an example script. The `Image...` button in the NPC palette sets the picture new NPCs start with |
| `Character` / `Empty NPC` | the green buttons on the right edge: press one and drag it onto the level to drop one NPC. A character comes with the quick character script (`showcharacter`, `setcharprop #3` head, `#8` body, colours `#C0`-`#C4`, shield, `dir`) and is drawn with its head and body in the level; an empty NPC opens an empty code window. Saved NPC templates (NPC palette) are dragged out the same way |
| `L` links | drag the warp rectangle, then type the destination level and the new position |
| `I` signs | click a tile and type the text |
| `Tab` | palette: tiles, saved tile objects (`Ctrl+B` saves the picked tiles, `Delete` removes the chosen one) and NPC templates (`Ctrl+Shift+B` saves the selected NPC, click one to place new NPCs from it) |
| `[` `]` | change the layer (0 to 7); everything you paint, pick, copy, fill and clear works on that layer |
| `+` `-` | zoom 2x / 1x |
| `Tileset...` | button above the palette: choose the tileset image (any image the client can find; remembered in `build_data/settings.json`, and used by `P` play) |
| `Ctrl+N/O/S`, `Ctrl+Shift+S` | new, open, save, save as. Open and the toolbar Save show a file browser (folders, a name field, double-click to enter a folder); `Ctrl+S` on a named level saves at once |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo (a whole paint stroke is one step) |
| `P` | save and play the level in the offline viewer |
| arrows, wheel, `F2` | scroll, grid |

In the dialogs Tab moves between fields, the arrow keys, Home, End and Delete edit the text (hold an arrow key, Backspace or Delete to repeat it), and Ctrl+Enter accepts a field with several lines. Saved objects and NPC templates are kept in `build_data/`. Build is offline: it shows images from the `asset_dirs` and from the client's download cache, so a head or body you have seen on the server shows up in Build too; one that is not on the computer is drawn as a plain figure with a `?` and named in the status line.

Build reads and writes the same `.nw` format as gs2emu (`BOARD`, `LINK`, `SIGN`, `CHEST`, `BADDY`, `NPC`). A server only loads a link whose destination level exists, so save the destination first. Not in Build: the flag editor and editor control NPCs. Build and the client are tested on Linux and with the Windows build of Python under Wine.

## Tests
```
python3 tests/run_tests.py --quick
```
Some tests need level and script data in the folders from `paths.json` and are skipped or fail without it. `ARCHITECTURE.md` describes how the modules (in `engine/`) fit together.
