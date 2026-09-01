# Contributing

Running the ring from source rather than the container, which is what you
want while changing it. [README.md](README.md) covers ordinary use;
[PLAN.md](PLAN.md) has the design notes and the protocol details that took
some digging to establish.

The code is four files: `apa102.py` drives the hardware, `animations.py`
holds the named animations and the runner that swaps between them, `main.py`
is the WebSocket client and the event-to-animation mapping, and
`test_leds.py` is a standalone hardware check.

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

## Hardware check

```sh
uv run python test_leds.py
```

All 12 LEDs cycle red, green, blue, off; then a single white pixel walks once
around the ring; then all 12 ramp brightness up and back down.

If red and blue are swapped, the per-LED byte order in `apa102.py` is wrong.
If nothing lights at all, GPIO5 is not being held high — that pin gates VCC to
the ring.

Useful flags: `--brightness 1-31`, `--hold`, `--step`, `--num-leds`.

## Running against LVA

```sh
uv run python main.py --record events.jsonl -v
```

Connects to `ws://localhost:6055`, drives the ring, and reconnects with
exponential backoff (1s doubling to 30s) whenever LVA goes away. `--record`
appends every event to a JSONL file, which is the quickest way to see what
LVA actually sends; `-v` adds raw traffic and the animation switches.

`--no-leds` runs it log-only, for a machine without the hardware or while the
container already holds the SPI device.

Stop the container first — two processes writing to `/dev/spidev0.0` and
GPIO5 will fight.

## Checks

```sh
uv run python tests/run_all.py
```

No Pi, ring or LVA needed — see [tests/README.md](tests/README.md) for what
each one covers. Worth running before and after a change; several of the
assertions pin down behaviour that looks wrong until you know why.

## Behaviour worth knowing before changing it

**Animations carry a `min_hold`.** LVA can pass through `thinking` in under a
second, so without a minimum display time some states would never be seen.
The cost is that a very short TTS reply can skip the speaking pulse entirely.

**Playback animations free-run.** `tts_speaking` carries no duration, so they
loop until something replaces them rather than being timed.

**The runner compares animations by identity.** Handing it a freshly built
object restarts whatever is playing, which is how a colour change takes
effect mid-animation — and why the light's colour presets are only applied
when the effect actually changes.

**Colour and brightness are separate from the hardware brightness field.**
The APA102's 5-bit field has 31 steps, far too few to dim smoothly, so
brightness scales the RGB values instead and `--brightness` is left alone as
the hardware ceiling.

## Deployment notes

The image installs `python3-spidev`, `python3-gpiozero` and
`python3-websockets` from Debian, so there is no compiler and no pip in it —
the same reasoning as the host setup above.

It does not use `lgpio`, which the host does. That package is Raspberry Pi
OS's rather than Debian's, and pulling in that archive means trusting a
signing key whose self-signature is SHA1 — rejected outright by trixie's
verifier since February 2026. Holding one pin high does not justify weakening
signature checking, so the container uses gpiozero's own `native` pin factory,
which is pure Python and maps `/dev/gpiomem`.

It needs three things from the host, all in `docker-compose.yml`:

- `network_mode: host`, because LVA runs that way and its peripheral API is
  only on the host's own localhost
- `/dev/spidev0.0`, the ring
- `/dev/gpiomem`, for GPIO5 which gates power to the ring — `privileged: true`
  is not needed. `/dev/gpiochip0` is mapped too, so switching pin factories
  later needs no compose change

There is deliberately no `depends_on`: LVA is a separate compose project, and
the reconnect loop copes with it being absent or restarting.

On this Pi it is deployed to `/compose/leds/`, which PiCompose picks up
automatically.

## Development on a non-Pi machine

`gpiozero` is marked `sys_platform == 'linux'`, so `uv sync` works on macOS
and installs only `websockets`. `spidev` and `lgpio` come from apt on the Pi
and are not pip dependencies at all.

`animations.py` deliberately imports no hardware at runtime, so the
animations and the event mapping can be exercised against a stand-in object
with `num_leds`, `set_pixel`, `fill`, `get_pixel`, `show` and `clear`. That is
how the behaviour above was tested without a ring attached. `main.py` imports
`apa102` only when LEDs are enabled, so `--no-leds` runs anywhere.
