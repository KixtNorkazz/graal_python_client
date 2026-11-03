# Architecture (map of client_re)

All modules below are in `engine/`; `start.py` and `build.py` in the project folder put it on the import path. Tools are in `tools/`, tests in `tests/`.

## Layers
1. **Wire**: `graalproto.py` (framing, zlib/bz2, XOR keys, Graal ints), `minclient.py` (login via listserver), `props.py` (player / NPC property parsing), `enums.py`.
2. **Session** `gclient.py` (`Session`): state of one client (level, pos, npcs, players, items, chests, weapons, flags, inventory props in `me`), packet handlers,
   walking (`step`, `walk_to`, missions, door planner glue), combat bits (`attack`, `hit_npcs`, `lift`/`throw`, horses, death).
   `Session.poll()` = network + `tick_all()` (runners, NPC runtime, projectiles, bombs, GUI, local NPC server, walks).
   `offline.py` (`OfflineSession`) = same class with no socket: loads `.nw` levels / gmaps (`nwlevel.py`), local inventory, save/load state.
3. **Scripts**
   - GS1: `weapons.py` (parser `parse`, `evaluate`, `run_nodes`, `yield_command`; weapons + NPCs share it) and `gs1.py` (visual effects of NPC commands, `Fx`).
   - GS2: `gs2src.py` (lexer, parser, generator evaluator), `gs2sched.py` (waitfor), `gs2npc.py` (NPC host, bridge to GS1 commands), `gui.py`, `particles.py`.
   - NPC runtime `npcrt.py` (`NpcRuntime`, `NpcInstance`): events, tweens, look-ahead on shadow sessions (`_shadow_session`, `_clone`), door analysis
     (`door_way`, `doors`, `flag_setter`, `sources`), NPC memory (`state_of`).
   - `npcserver.py` + `weaponlib.py`: local stand-in for the NPC server (server parts of GS2 weapons, other players, loopback triggers).
   - `inputs.py` (keys / mouse), `projectiles.py`, `bombs.py`, `audio.py`.
4. **World**: `collision.py` (tile types from `tiletypes.py` + NPC shapes), `pathing.py` (A* on the 8-px lattice, soft / time-aware costs), `assets.py` (find files).
5. **Output**: `render.py` (`render_scene`, `draw_hud`, depth order), `gani.py`, `window.py` + `viewer.py` (SDL2 via ctypes), `valview.py` (png of a level).

## Data flow of a planned walk (`Session.walk_to`)
`walk_to` -> A* with costs (`_plan_costs`: players, moving NPCs, doors, pushables) -> `_door_prelude` asks `npcrt.doors()` which door NPCs on the path can be opened
(`door_way` simulates triggers x modifiers on shadow sessions) -> `acquire_plan` makes steps for missing flags / items / weapons (ground items, chests, `npcrt.sources()`
shops and givers) -> mission steps (`say`, `touch`, `pickup`, `get`) -> `_walk_tick` walks, at a door `_door_action` does the trigger (chat, keys, grab, sword, bomb,
arrow, lift) -> `_walk_done`.

## Conventions
- Positions: level-local px (`Session.pos`), gmap-global px = cell*1024 + local; NPC `Fx.x/y` in tiles; projectiles / bombs in gmap-global tiles.
- NPC ids: server NPCs are ints, offline NPCs are `(level_file, index)` tuples. Packets about NPCs are only sent for int ids.
- Never name a Session method `chat` (it is the chat log list). Simulations run on shadow sessions with a command budget; they must not touch the real session.
- Live tests: the password is only read from the environment variable GRAAL_PASSWORD.

- Classes (`join X;`): `offline.class_text` searches the `class_dirs` folders, then `classes/`, then the `server_script_dirs` folders; `_`, `-` and spaces in a name are equal. A class file whose first line is `//#SERVERCLASS` runs in the NPC's server part (chat / touch / action events); other classes are added to the client part. A class found in `class_dirs` wins over `classes/`.
- GS1 expressions are evaluated by translating them to Python in `weapons.evaluate` (arrays `this.a[i]`, lists `{..}`, `x in list`, `tiles[x,y]`, hex, `^`, `x-2` arithmetic). Anything that fails evaluates to 0 silently: run `evalfail_survey.py` after changes to see what fails.
- Folders (assets, classes, weapons, accounts) come from `config.py` / `paths.json`; code must not hard-code a path. Use `config.dirs(key)`.

## Tools
`python3 run_tests.py [--quick] [--live]` all tests + surveys; `npcsurvey.py [n] [--gs2]`, `walk_survey.py [n]`, `gs2weapons_survey.py`, `gs1survey.py`, `evalfail_survey.py` (expressions that silently become 0);
`simulate_two.py` (live, two accounts); `viewer.py --offline X.gmap --state FILE`; `valview.py level.nw out.png`.
