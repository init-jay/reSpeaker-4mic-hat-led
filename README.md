# reSpeaker-4mic-hat-led

Drive the 12 APA102 LEDs on the ReSpeaker 4-Mic Array from Linux Voice
Assistant's peripheral WebSocket API. See [PLAN.md](PLAN.md).

## Setup (on the Pi)

`lgpio` (gpiozero's pin factory) and `spidev` both build C from PyPI — lgpio
additionally wants SWIG and the lgpio C library. Raspberry Pi OS ships both
prebuilt, so install them from apt and let the venv see the system path. No
compiler needed:

```sh
sudo apt install -y python3-lgpio python3-spidev
rm -rf .venv
uv venv --system-site-packages --python /usr/bin/python3
uv sync
```

The `--python /usr/bin/python3` matters: the apt packages are installed for the
system interpreter, so a uv-managed Python would not find them. Check with

```sh
uv run python -c "import lgpio, spidev; print(lgpio.__file__)"
```

which should print a path under `/usr/lib/python3/dist-packages`.

`uv sync` recreates `.venv` if it disagrees with the project, and a recreated
one loses `--system-site-packages`. If `lgpio` or `spidev` stop importing, run
the `uv venv` line again.

## Phase 1 — hardware check

```sh
uv run python test_leds.py
```

All 12 LEDs cycle red, green, blue, off; then a single white pixel walks once
around the ring; then all 12 ramp brightness up and back down.

If red and blue are swapped, the per-LED byte order in `apa102.py` is wrong.
If nothing lights at all, GPIO5 is not being held high — that pin gates VCC to
the ring.

Useful flags: `--brightness 1-31`, `--hold`, `--step`, `--num-leds`.

## Phase 2 — event stream

```sh
uv run python main.py --record events.jsonl
```

Connects to `ws://localhost:6055`, logs every event, and reconnects with
exponential backoff (1s doubling to 30s) whenever LVA goes away. `--record`
appends each event to a JSONL file, which is what Phase 3 maps to animations.
`--uri` points it elsewhere, `-v` adds raw traffic.

Trigger the wake word and watch the pipeline events arrive. Ctrl-C to stop.

## Phase 3 — animations

The same command drives the ring. `--brightness 1-31` sets the ceiling
(default 5 — 12 LEDs at full brightness is a lot in a room), `--no-leds` runs
log-only on a machine without the hardware.

| State | Ring |
|---|---|
| idle | dark, fading out from whatever was showing |
| wake word | bright purple flash settling to a steady ring |
| listening | slow purple breath |
| thinking | purple comet, one turn every 0.9s |
| speaking | faster purple pulse until `tts_finished` |
| muted | solid red |
| volume changed | purple bar, one second |
| pipeline error | three red flashes, then back |
| timer ringing | alternating amber halves |
| LVA unreachable | red twinkle |
| HA unreachable | amber twinkle |

Every pipeline state is purple and is told apart by movement. Red and amber
mean something is wrong: red for muted or unreachable LVA, amber for LVA being
up but unable to reach Home Assistant.

## Phase 4 — Home Assistant light

On connect the ring registers itself as a Light entity (`led_ring`, "LED
Ring") under the ESPHome device, supporting RGB, brightness and three effects.
It re-registers on every reconnect, since a restarted LVA has forgotten it.

The entity owns the ring:

| Entity state | Ring |
|---|---|
| off | dark; the pipeline does not draw |
| on, "Voice Assistant" effect | the status animations above (the default) |
| on, "Rainbow" | hues rotating once every four seconds |
| on, "Breathe" | slow breath in the chosen colour |
| on, no effect | solid, in the chosen colour |

So the ring can be used as a small lamp, and the voice animations stay out of
the way until the effect is switched back.

The colour picker sets the colour of the pipeline animations too, so the
status ring is whatever colour you choose — purple until you change it. Faults
keep their own colours, since a red twinkle that could be recoloured green
would not be much of a warning.

Brightness from HA is applied to the colour values, not to the APA102's
brightness field, which has only 31 steps. That matters more than it sounds:
LVA normalises colour so the largest channel is always 1.0 and folds the
intensity into `brightness`, so *every* colour change carries a brightness
change with it. Through the 5-bit field those landed as a handful of coarse
jumps, which made choosing a colour a fight. `--brightness` stays fixed as the
hardware ceiling for the room.

## Development on a non-Pi machine

`gpiozero` is marked `sys_platform == 'linux'`, so `uv sync` works on macOS and
installs only `websockets`. `spidev` and `lgpio` come from apt on the Pi and
are not pip dependencies at all. The LED code imports the hardware modules at
module scope and will not run off the Pi.
