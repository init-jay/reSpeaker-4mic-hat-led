# reSpeaker 4-Mic LED Ring

Turns the 12 LEDs on a ReSpeaker 4-Mic Array into a status ring for
[Linux Voice Assistant](https://github.com/OHF-Voice/linux-voice-assistant):
the ring lights when the wake word fires, animates through listening,
thinking and speaking, and shows you when something is wrong.

It also registers itself in Home Assistant as a light, so you can recolour it,
dim it on a schedule, or turn it off at night.

<!-- Hosted on GitHub's asset CDN rather than committed, so it renders as an
     inline player. It has to stay a bare URL on its own line for that to
     work; wrapping it in markdown turns it back into a link. -->

https://github.com/user-attachments/assets/8bb6fda4-4476-4893-b293-29563571e7db

Demo of the LED ring tracking a voice interaction.

## Requirements

- A Raspberry Pi with a ReSpeaker 4-Mic Array HAT
- Linux Voice Assistant already running on it, with its peripheral API on
  `ws://localhost:6055` (the default)
- Docker with the compose plugin

[PiCompose](https://github.com/florian-asche/PiCompose) is the recommended way
to get Linux Voice Assistant onto the Pi in the first place, and is what this
was built against. It deploys anything under `/compose/`, so if you are using
it, put this there and it will be picked up like the rest.

SPI is enabled by the `seeed-4mic-voicecard` overlay, so `/dev/spidev0.0`
should already exist. Check with `ls /dev/spidev*`.

## Install

```sh
git clone https://github.com/init-jay/reSpeaker-4mic-hat-led
cd reSpeaker-4mic-hat-led
docker compose up -d --build
```

Under PiCompose, clone it to `/compose/leds` instead and it deploys itself.

That is the whole install. The ring should light up the next time you use the
wake word.

To watch what it is doing:

```sh
docker compose logs -f
```

## What the ring shows

| State | Ring |
|---|---|
| idle | dark, fading out from whatever was showing |
| wake word | bright flash settling to a steady ring |
| listening | slow breath |
| thinking | comet, one turn every 0.9s |
| speaking | faster pulse, until speech ends |
| volume changed | a bar showing the new level, one second |
| muted | solid red |
| timer ringing | alternating amber halves |
| pipeline error | three red flashes, then back |
| LVA unreachable | red twinkle |
| Home Assistant unreachable | amber twinkle |

The pipeline states are all one colour — purple unless you change it — and are
told apart by how they move. Red and amber always mean something is wrong.

## Home Assistant

The ring appears as a light called **LED Ring** under your existing Linux
Voice Assistant device, alongside its other entities. Nothing to configure: it
registers itself on connect.

| Effect | Ring |
|---|---|
| Voice Assistant | the animations above, in purple (the default) |
| Green / Red / Yellow | the same, in that colour |
| Rainbow | hues rotating once every four seconds |
| Breathe | slow breath in the colour last chosen |
| no effect | solid colour |

The first four keep the ring working as a status display. The last three turn
it into a small lamp and stop the voice animations drawing over it.

The colour wheel works too, and applies to the voice animations — so the
status ring can be any colour you like. Faults keep their own red and amber
regardless, since a warning you can recolour is not much of a warning.

The brightness slider dims everything, and is a good thing to put on a
schedule if the ring is somewhere you sleep. Turning the light off leaves the
ring dark even during a conversation.

> If the entity does not appear, restart Linux Voice Assistant while this
> container is running. It only publishes its entity list on startup, so it
> needs to see the ring register.

## Configuration

Flags go on the `command:` line in `docker-compose.yml`; then
`docker compose up -d`.

| Flag | Default | Meaning |
|---|---|---|
| `--brightness` | `5` | Hardware ceiling, 1-31. 12 LEDs at full brightness is a lot in a room; the Home Assistant slider dims within this |
| `--uri` | `ws://localhost:6055` | Where to find the peripheral API |
| `--num-leds` | `12` | Ring size |
| `-v` | off | Log raw traffic, for when something is not behaving |

## If something is wrong

**Nothing lights up at all.** GPIO5 gates power to the ring, so this usually
means GPIO is not reachable. Check `/dev/gpiomem` exists and that the
container has it mapped.

**The ring is dark but the logs look fine.** Idle *is* dark. Say the wake word
and see whether it responds. Also check the light is not switched off in Home
Assistant.

**Red twinkle that does not stop.** The container cannot reach Linux Voice
Assistant. It keeps retrying, so this clears by itself once LVA is back.

**Amber twinkle.** LVA is running but cannot reach Home Assistant. Look at
LVA, not at this.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for running from source, the hardware
test script, and how the pieces fit together. [PLAN.md](PLAN.md) has the
design notes and what the peripheral API actually sends.
