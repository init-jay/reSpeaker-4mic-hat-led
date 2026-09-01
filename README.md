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

## Development on a non-Pi machine

`gpiozero` is marked `sys_platform == 'linux'`, so `uv sync` works on macOS and
installs only `websockets`. `spidev` and `lgpio` come from apt on the Pi and
are not pip dependencies at all. The LED code imports the hardware modules at
module scope and will not run off the Pi.
