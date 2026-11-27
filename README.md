# CoreBall

**English** | [中文](README.zh-CN.md)

A spherical AI companion robot. Personality and memory live inside the ball, and the ball mounts onto different bodies — **one soul, any body**.

Inspired by the childhood IP *超能 NoNo*; the look and the fiction are entirely original.

---

## Where it stands

**Closed on paper, not started on the bench.**

The mechanism, dimensions, control and behaviour are all drawn, and it renders and animates.
**Not a single physical part exists yet.**

- Everything is parametric — change one number and re-run.
- Everything is computed, not drawn by feel: tension, clearance and the flyable zone all have numbers.
- Not one line of code serves "cute". Cute lives in the renders and the motion curves.

---

## Layout

```
README.md                 English
README.zh-CN.md           中文
TODO.md                   open work and known issues
docs/
  00-规格书.md             initial spec (v0.1, untouched)
  01-设计决定.md           every trade-off: decision / why / cost
  02-控制架构.md           five-layer structure, tension math, keep-out zones, paths, curves
  03-参数表.md             every dimension and number, in one place
  04-接口标准.md           frozen φ30 well, keys, magnets, pinout
  05-核心构造对比.md       prototype core options
  06-可达空间.md           coverage test for the eight wall anchors
  07-开发日志.md           dated log: what / why / how it was verified
  08-技术报告.md           current snapshot: goals, parameters, coverage, control, risks, next
  archive/                abandoned directions (the first desk box, the electromagnetic station)
web/
  viewer.html             offline WebGL viewer (plug-in animation + 3D ball/rig)
  command.html            3D command page
  control.html            operator console (quick actions + manual + expressions + camera/2D/3D)
  操作台.bat              one-click launcher: Blender + bridge + console
  操作台窗口.bat          one-click single app window: camera left, console right
blender/
  build_ball.py           the core ball, φ80
  build_hub.py            hub assembly (yaw + extension); renders on its own
  build_desk_rig.py       station + eight wall-mounted winches
  build_winch.py          winch assembly, two variants
  build_anim.py           eight-second motion clip → mp4
  build_command.py        command scene: drag CMD_TARGET, ball and all eight lines follow live
  cmd_runtime.py          panel, keep-out zone, intent channel (started by 指挥.bat)
  actions.json            actions and phrases — editable
  指挥.bat                double-click to enter the command scene
  out/                    every render
tools/
  tension.py              tension-allocation calculator (choose 4 of 8)
  optimize_anchors.py     wall-anchor coverage search
  control_server.py       bridge from the control page to UDP
  plan.py                 path planning
  curves.py               speed-curve comparison
  storyboard.py           "a day in its life" storyboard
```

---

## Running it

Replace `<path-to-blender.exe>` with the Blender executable on your machine.

```powershell
# Blender lives here
set B=<path-to-blender.exe>

# Renders
& $B --background --python blender\build_ball.py      -- --out blender\out\ball  --render
& $B --background --python blender\build_desk_rig.py  -- --out blender\out\rig   --render
& $B --background --python blender\build_winch.py     -- --out blender\out\winch --render
& $B --background --python blender\build_hub.py       -- --out blender\out\hub   --render

# Command scene: drag CMD_TARGET, all eight lines follow live
& $B --background --python-exit-code 1 --python blender\build_command.py -- --out blender\out\cmd

# Animation (about ten minutes)
& $B --background --python blender\build_anim.py      -- --out blender\out\anim

# Computation (pure Python, no Blender)
python tools\tension.py -380 520 1300    # ball centre; solved at the hub (+160), 4 of 8 picked
python tools\export_params.py            # after changing tension params, sync to web\params.json
python tools\zone_map.py
python tools\plan.py
python tools\curves.py
python tools\storyboard.py
```

`blender\重建.bat` and `blender\打开场景.bat` are there for double-clicking.

## Browser preview (no Blender)

Double-click `web\serve.bat`; it opens <http://localhost:8000/web/viewer.html>.

- Four views: ball / hub plug / full booth / insert animation;
- Drag to orbit, wheel to zoom, works on a phone;
- Fully offline; the models are local GLBs.

Re-export after a model change:

```powershell
& $B --background --python tools\export_models.py   # ball / hub / rig
& $B --background --python tools\export_insert.py   # plug insert animation
```

## Protocol simulation (no hardware)

```powershell
python tools\test_protocol.py
python tools\sim_link.py
```

`sim_link.py` runs ball and carrier with real frames and CRC: top 4-pin works, a 3 A carrier on the top is refused, bottom 3 A works, silence becomes "dumb", and a bad CRC is retried.

The online Wokwi version is in `wokwi\README.md`: one ESP32 and two crossed UART wires.

### 2D / 3D operator console

Double-click `web\操作台窗口.bat` (recommended): it starts Blender's command scene, the local bridge and the camera, then opens a single Edge/Chrome app window — **live camera on the left, console on the right**. To open only the page, use `web\操作台.bat` or `web\control.bat`.

- Left tabs: **live camera** (USB camera + hand skeleton) / **3D rig** / **2D map**;
- The first screen is a three-step guide. If Blender is not running, click "先看演示" to explore a simulated ball; it never commands real hardware;
- **Quick actions**: come / back / look / stop;
- **Manual**: hold the on-screen arrows or W/A/S/D, Q/E for height, release to stop; click the floor to go to a point; Space stops;
- **3D rig**: booth, ball, hub, eight cables and the red neck cylinder update live; drag to orbit, wheel to zoom;
- **2D map**: top-down position, click to go;
- **Status and ropes**: support set, per-rope tension, loosest tension and safety layer, folded into a details panel;
- **Expressions**: idle / listening / acting;
- The page shows Blender's **actual position** (ball / hub), not the commanded target;
- Telemetry goes from Blender to UDP 4591 and is cached by the bridge at `GET /state`; the event log can be exported;
- The ball center is clamped inside the three walls (x ±775, y **250–1055**; the first 250 mm in front of the back wall is outside the practical workspace, see decision 29).

Manual control has a dead-man switch: if the console stops sending for 0.35 s, Blender stops on its own.

## Commanding it

Double-click `blender\指挥.bat`, then:

- Drag `CMD_TARGET` directly — ball, hub and all eight candidate lines move together.
- Keys `1` come · `2` go back · `3` up · `4` down · `5` look at me · `0` stop.
- Any program can send a UDP command:
  ```powershell
  $u = New-Object Net.Sockets.UdpClient
  $b = [Text.Encoding]::UTF8.GetBytes('{"intent":"come"}')
  $u.Send($b, $b.Length, '127.0.0.1', 4590)
  ```
- Actions, phrases and speeds live in `blender\actions.json`; edit, then restart `指挥.bat`.

### Changing bodies

- `python brain.py --mount rover` → the core moves into a small ground robot (ball hidden inside, only the core light showing)
- `python brain.py --mount winch` → back to the cable rig
- You can also just say "switch to the rover" / "back to the rig"
- On a switch, **an unfinished goal is handed to the new body**; whatever the new body cannot do (the rover cannot lift, for instance) is refused outright instead of faked
- The rover moves on the ground only (x/y + heading); the HUD switches to "rover · ground · no cables"

## The brain (type → the ball moves)

1. Copy `brain.example.json` to `brain.json` and put your DeepSeek key in `providers.deepseek.api_key` (`brain.json` is gitignored and never committed).
2. `python brain.py`, then just type; when a reply carries an action, the ball moves over UDP.
3. Personality is written in `persona.md`; memory lives in `memory/` (append-only, compacted when it fills).
4. To use Kimi for memory: set `roles.memory` to `kimi` and add its key.
5. Self-check: `python tools\test_brain.py`

## Letting it speak

- Default is **auto**: with `appid` and `token` filled under `voice.volcengine` in `brain.json` (or `voice.json`) it uses **Volcengine**; otherwise it falls back to **Windows offline speech** — zero cost, no signup. `python voice.py "hello"` and it talks.
- Volcengine console: Speech → Text-to-Speech → create an app, take the APPID and Access Token.
- Force local only: set `provider` (or `backend` in voice.json) to `windows`.

---

## Key numbers

| Item | Value |
|---|---|
| Ball | φ80, ~260 g, fits in one hand |
| Hub assembly | ~240 g, 360° yaw, 90 mm extension |
| Station | 1640 × 1100 × 1900 mm |
| Cables | 8 candidates (4 load-bearing + 4 idle) + 1 power (twinned) |
| Current cable lengths | 1331 / 645 / 766 / 661 mm |
| Slackest tension | 2.31 N (ample margin) |
| Flyable zone | 100% of sampled workspace at the hub (practical zone 100%), ~0.6 m³ usable |
| Keep-out zone | r210 hard / r305 soft, centred on the neck |
| Default pose | (−380, 520, 1300), 640 mm from the eyes, 30° off centre |

---

## The project in three sentences

1. **It cannot do everything.** It does one thing: sit beside you and express attitude through position and posture.
2. **It floats on four cables, not on anti-gravity.** The strings are its grammar, not its flaw.
3. **Personality is not on the shortest path; it is on the boundary.** In open space everyone walks the same line — hugging the keep-out zone is where character shows.

---

## Next

See `TODO.md`. The recommended first step is **freezing the interface standard** — it is the one thing every later part hangs off, and the longer you leave it, the more it costs.

---

## License

MIT

