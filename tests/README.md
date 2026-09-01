# Checks

```sh
uv run python tests/run_all.py
```

None of these need a Pi, a ring, or a running Linux Voice Assistant. `apa102.py`
is the only module that touches hardware, and `main.py` imports it lazily, so
everything else can be driven against a fake ring that records the frames it is
asked to show.

| Check | Covers |
|---|---|
| `check_frames.py` | The bytes `apa102.py` would put on the wire: frame layout, per-LED byte order, brightness, clamping, GPIO5 |
| `check_animations.py` | Animations and event mapping, replaying a real captured interaction at the pace it arrived |
| `check_light.py` | The Home Assistant light: payload coercion, off/lamp/voice modes and their priority, colour and brightness, reconnect signalling |
| `check_client.py` | The WebSocket client against a stand-in LVA: dispatch, malformed messages, commands, reconnect backoff, shutdown |

They are assertion scripts rather than a pytest suite, so they need nothing
beyond `websockets` and run the same way everywhere. Each exits non-zero on the
first failed assertion and prints what it expected.

Several of the assertions exist because the behaviour they check is not
obvious, and would look like a bug worth "fixing":

- `thinking` survives `tts_speaking` arriving 50ms later, because LVA can pass
  through that state in under a second and it would otherwise never be seen
- an unrelated event must not restart a running effect — the runner compares
  animations by identity, so rebuilding one is how a recolour takes effect
- a state echo repeating the current effect must not reset a colour set on the
  wheel, since LVA repeats the whole light state in every command
- faults keep red and amber whatever colour is selected

Timing-sensitive checks sleep in fractions of a second. On a very loaded
machine they can be flaky; rerun before believing a failure.
