# LED Peripheral for Linux Voice Assistant — ReSpeaker 4-Mic Array

Drive the 12 APA102 LEDs on the ReSpeaker 4-Mic Array from LVA's peripheral
WebSocket API, replacing the `4mic_leds.service` that ran under
wyoming-satellite.

## Context

| Item | Value |
|---|---|
| Host | Raspberry Pi 3, wlan0 |
| OS | Raspberry Pi OS, kernel `6.18.34+rpt-rpi-v8` |
| Sound card | `seeed4micvoicec` (card 1), AC108 @ I2C `0x3b` |
| Driver | `init-jay/seeed-voicecard-4mic`, branch `v6.14` (ported to 6.18) |
| LEDs | 12x APA102 on SPI, `/dev/spidev0.0` |
| LVA | v1.1.15, container `linux-voice-assistant`, `network_mode: host` |
| Peripheral API | `ws://localhost:6055` |
| Compose root | `/compose/` (managed by PiCompose) |

## Hardware notes

**GPIO5 must be driven HIGH to enable VCC to the LED ring.** Per Seeed's wiki
for this board, the APA102s are unpowered until this is done. This is the most
common reason correct SPI code appears to do nothing. Do this once at startup
before any SPI writes.

APA102 protocol over SPI:
- Start frame: 4 bytes of `0x00`
- Per LED: `0xE0 | brightness(5 bits)`, then B, G, R (note the ordering)
- End frame: at least `n/2` bits of `0xFF`; 4 bytes of `0xFF` is sufficient for 12 LEDs

SPI is enabled by the `seeed-4mic-voicecard` overlay itself — `dtparam=spi=on`
is not required in `config.txt` and is currently commented out. Confirm with
`ls /dev/spidev*` after any overlay change.

## Protocol summary

Reference: `/app/linux_voice_assistant/peripheral_api.py` inside the container.

JSON over WebSocket, both directions:

```
Events   (LVA -> peripheral):  {"event": "<name>", "data": {...}}
Commands (peripheral -> LVA):  {"command": "<name>", "data": {...}}
Snapshot (on connect):         {"event": "snapshot", "data": {...}}
```

Events we care about, in rough pipeline order:

| Event | Animation |
|---|---|
| `wake_word_detected` | Bright flash, full ring |
| `listening` | Steady or slow pulse while mic is open |
| `thinking` | Spinner / chase |
| `tts_speaking` | Pulse in time with playback |
| `tts_finished` | Fade to idle |
| `idle` | Off, or very dim |
| `muted` | Solid red (`data: {"muted": bool}`) |
| `pipeline_error` | 3 red flashes, then idle |
| `disconnected` | Red twinkle, retry until `zeroconf` reports `connected` |
| `timer_ringing` | Attention animation |
| `volume_changed` | Brief level indication on the ring |

`light_command` arrives when HA changes a Light entity we registered — carries
`object_id`, `state`, `brightness`, `red`, `green`, `blue`, `effect`. The effect
names are the ones we declare at registration.

## Phases

### Phase 1 — Standalone LED test

Prove the hardware before involving LVA at all.

- [x] Write `apa102.py`: SPI init, GPIO5 enable, `set_pixel`, `show`, `clear`
- [x] Source the APA102 logic from wyoming-satellite `examples/4mic_leds.py`
- [x] Test script: cycle all 12 LEDs through red, green, blue, off
- [x] Confirm brightness control works and there's no flicker

Exit criteria: LEDs respond to a script run directly on the host.

### Phase 2 — WebSocket client

- [x] `main.py`: connect to `ws://localhost:6055`, log every event received
- [x] Handle the `snapshot` event on connect to pick up initial state
- [x] Reconnect loop with backoff — a WebSocket failure means LVA is down,
      which is itself a "disconnected" condition and should show that animation
- [ ] Trigger the wake word and confirm the expected event sequence arrives

Exit criteria: full event stream logged during a voice interaction.

### Phase 3 — Animations

- [ ] Animation loop on its own task so long animations don't block the socket
- [ ] Map each event to an animation; cancel the running one on state change
- [ ] Tune brightness — 12 LEDs at full brightness in a kitchen is a lot
- [ ] Implement `disconnected` and `pipeline_error` as specified above

Exit criteria: LEDs track a full voice interaction end to end.

### Phase 4 — HA Light entity

- [ ] Send `register_light` on connect:
      `{"name": ..., "object_id": ..., "effects": [...], "supports_rgb": true, "supports_brightness": true}`
- [ ] Handle `light_command`, matching on `object_id`
- [ ] Declare a `"Voice Assistant"` effect that runs the pipeline animations,
      plus any static effects worth exposing
- [ ] Confirm the entity appears in HA under the ESPHome device

Note: LVA PR #373 fixed a race between LVA registering with HA and peripherals
registering their entities. `--peripheral-startup-wait` (default 2.0s) governs
how long LVA waits. If the entity doesn't appear in HA, raise it.

### Phase 5 — Deployment

Compose project at `/compose/leds/`, consistent with PiCompose, which
auto-deploys anything under `/compose/`. Needs:
- `network_mode: host` to reach port 6055
- `devices: - /dev/spidev0.0:/dev/spidev0.0`
- `/dev/gpiomem` mapped, or `privileged: true` for GPIO5
- `depends_on` won't help across compose projects — rely on the reconnect loop

- [ ] Write `Dockerfile` and `docker-compose.yml`
- [ ] Deploy under `/compose/leds/` and confirm PiCompose picks it up
- [ ] Verify it survives a reboot
- [ ] Verify it recovers when LVA restarts

## Out of Scope

- Direction of arrival: the 4-mic array can estimate DOA, and the LED ring was
  designed to show it. LVA exposes no DOA data, so this would mean processing
  the 4-channel capture separately. Out of scope, but the hardware supports it.

## Repo layout

```
lva-leds/
├── PLAN.md
├── apa102.py           # SPI + GPIO5, low-level LED control
├── test_leds.py        # Phase 1 hardware check
├── animations.py       # named animations, cancellable
├── main.py             # websocket client, event dispatch
├── pyproject.toml      # uv project: websockets, spidev, gpiozero, lgpio
├── docker-compose.yml
└── Dockerfile
```

## Related work

The seeed-voicecard kernel 6.18 port lives at
`github.com/init-jay/seeed-voicecard-4mic` (branch `v6.14`). Three fixes:
DAIFMT constant renames, the `SOC_SINGLE_VALUE` min argument, and replacing the
`simple_util_*` helpers whose signatures changed.