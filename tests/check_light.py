"""Exercise the Home Assistant light entity behaviour.

Covers the payload coercion, the off/lamp/voice modes and their priority, how
brightness and colour reach the ring, and the reconnect signalling — all of it
using payloads shaped the way LVA actually sends them.

    uv run python tests/check_light.py
"""

import asyncio

from fakes import FakeRing, add_repo_to_path

add_repo_to_path()

import animations  # noqa: E402
from main import LedDirector, _as_bool, _as_byte  # noqa: E402


async def main():
    # --- payload coercion ---------------------------------------------------
    assert _as_bool(True) and not _as_bool(False)
    assert _as_bool("ON") and _as_bool("on") and not _as_bool("off")
    assert _as_bool(1) and not _as_bool(0)
    assert _as_bool(None) is True  # default when absent
    assert _as_byte(255, 0) == 255
    assert _as_byte(0.5, 0) == 128, "0-1 floats are normalised"
    assert _as_byte(1.0, 0) == 255
    assert _as_byte(200, 0) == 200, "0-255 ints pass through"
    assert _as_byte(None, 42) == 42
    assert _as_byte(True, 42) == 42, "bool is not a channel value"

    ring = FakeRing(global_brightness=5)
    runner = animations.AnimationRunner(ring)
    director = LedDirector(runner)

    reg = director.registration
    assert reg["object_id"] == "led_ring"
    assert reg["supports_brightness"] and reg["supports_rgb"]
    for colour in ("Voice Assistant", "Green", "Red", "Yellow"):
        assert colour in reg["effects"], reg["effects"]
    assert reg["effects"][0] == "Voice Assistant", reg["effects"]

    # --- defaults to the voice pipeline before HA says anything -------------
    await director.on_connected()
    await director.on_event("wake_word_detected", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'wake', runner.current

    # --- turning the light off wins over everything -------------------------
    await director.on_event("light_command", {"object_id": "led_ring", "state": False})
    # wake's min_hold (0.3s) then the off fade (0.5s)
    await asyncio.sleep(1.1)
    assert runner.current is animations.OFF, runner.current
    assert ring.frames[-1] == [(0, 0, 0)] * 12, "off should be dark"

    await director.on_event("listening", {})
    await asyncio.sleep(0.05)
    assert runner.current is animations.OFF, "pipeline must not draw while off"

    await director.on_event("pipeline_error", {})
    await asyncio.sleep(0.1)
    assert runner.current is animations.OFF, "one-shots must not draw while off"

    # --- back on, as a lamp -------------------------------------------------
    await director.on_event("light_command", {
        "object_id": "led_ring", "state": True, "effect": "None",
    })
    await asyncio.sleep(0.1)
    assert runner.current.name.startswith("solid"), runner.current
    assert ring.frames[-1][0] == animations.PURPLE, ring.frames[-1][0]

    lamp = runner.current
    await director.on_event("thinking", {})
    await asyncio.sleep(0.05)
    assert runner.current is lamp, "pipeline must not hijack lamp mode"
    await director.on_event("volume_changed", {"volume": 0.5})
    await asyncio.sleep(0.1)
    assert runner.current is lamp, "one-shots must not hijack lamp mode"

    # a refresh that changes nothing must not restart the effect
    await director.on_event("idle", {})
    await asyncio.sleep(0.05)
    assert runner.current is lamp, "effect animation restarted on an unrelated event"

    # --- brightness rides on RGB, not the 5-bit hardware field --------------
    await director.on_event("light_command", {
        "object_id": "led_ring", "state": True, "effect": "None",
        "brightness": 1.0,
    })
    await asyncio.sleep(0.1)
    assert ring.global_brightness == 5, "hardware ceiling must not be touched"
    full = ring.frames[-1][0][0]

    levels = []
    for step in (0.8, 0.6, 0.4, 0.2, 0.1, 0.05):
        await director.on_event("light_command", {
            "object_id": "led_ring", "brightness": step,
        })
        await asyncio.sleep(0.06)
        levels.append(ring.frames[-1][0][0])
    assert ring.global_brightness == 5, "hardware ceiling must not be touched"
    assert levels == sorted(levels, reverse=True), f"not monotonic: {levels}"
    assert len(set(levels)) == len(levels), f"steps collapsed together: {levels}"
    assert levels[0] < full and levels[-1] < levels[0] // 4, (full, levels)

    # --- a static voice state follows the brightness too --------------------
    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Voice Assistant", "brightness": 1.0,
    })
    await director.on_event("muted", {"muted": True})
    await asyncio.sleep(0.2)
    assert runner.current.name == 'muted', runner.current
    bright_red = ring.frames[-1][0][0]
    ring.frames.clear()
    await asyncio.sleep(0.2)
    assert not ring.frames, "muted should park after drawing, not spin"

    await director.on_event("light_command", {"object_id": "led_ring", "brightness": 0.25})
    await asyncio.sleep(0.1)
    assert ring.frames, "brightness change did not redraw a parked static state"
    assert runner.current.name == 'muted', "redraw should keep the same state"
    dim_red = ring.frames[-1][0][0]
    assert 0 < dim_red < bright_red, f"muted did not dim: {dim_red} vs {bright_red}"
    assert ring.frames[-1][0][1] == 0, "muted must stay red whatever the picker says"

    await director.on_event("muted", {"muted": False})
    await director.on_event("light_command", {"object_id": "led_ring", "brightness": 1.0})
    await asyncio.sleep(0.1)

    # --- named effects ------------------------------------------------------
    await director.on_event("light_command", {"object_id": "led_ring", "effect": "Rainbow"})
    await asyncio.sleep(0.15)
    assert runner.current.name == "rainbow", runner.current
    hues = {tuple(p) for p in ring.frames[-1]}
    assert len(hues) > 6, f"rainbow should spread hues, got {len(hues)}"

    await director.on_event("light_command", {"object_id": "led_ring", "effect": "breathe"})
    await asyncio.sleep(0.1)
    assert runner.current.name.startswith("breathe"), "effect match is case-insensitive"

    await director.on_event("light_command", {"object_id": "led_ring", "effect": "Nonsense"})
    await asyncio.sleep(0.1)
    assert runner.current.name.startswith("solid"), "unknown effect falls back to solid"

    # --- returning to the voice effect resumes the pipeline -----------------
    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Voice Assistant",
    })
    await asyncio.sleep(0.05)
    assert runner.current is animations.IDLE, runner.current
    await director.on_event("tts_speaking", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'speaking', runner.current

    # --- the effect list doubles as a colour palette ------------------------
    # Every one of these effects still runs the voice pipeline, just in a
    # different colour.
    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Green", "brightness": 1.0,
    })
    await director.on_event("listening", {})
    await asyncio.sleep(0.2)
    assert runner.current.name == "listening", "a colour effect must stay in voice mode"
    r, g, b = ring.frames[-1][0]
    assert g > r and g > b, f"green not applied: {ring.frames[-1][0]}"

    await director.on_event("light_command", {"object_id": "led_ring", "effect": "Yellow"})
    await asyncio.sleep(0.2)
    assert runner.current.name == "listening", "recolour should not change state"
    r, g, b = ring.frames[-1][0]
    assert r > 0 and g > 0 and b == 0, f"yellow not applied: {ring.frames[-1][0]}"

    await director.on_event("light_command", {"object_id": "led_ring", "effect": "Red"})
    await asyncio.sleep(0.2)
    r, g, b = ring.frames[-1][0]
    assert r > 0 and g == 0 and b == 0, f"red not applied: {ring.frames[-1][0]}"

    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Voice Assistant",
    })
    await asyncio.sleep(0.2)
    r, g, b = ring.frames[-1][0]
    assert r > 0 and b > r, f"purple not restored: {ring.frames[-1][0]}"

    # a lamp effect keeps the colour last chosen
    await director.on_event("light_command", {"object_id": "led_ring", "effect": "Breathe"})
    await asyncio.sleep(0.1)
    assert runner.current.name.startswith("breathe"), runner.current
    assert not director._voice_mode, "a lamp effect must leave voice mode"

    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Voice Assistant",
    })
    await director.on_event("listening", {})
    await asyncio.sleep(0.15)

    # --- a colour from the wheel is honoured, and survives state echoes ------
    # LVA repeats the effect in every command, so the preset must only apply at
    # the moment it is selected or it would overwrite the wheel each time.
    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Voice Assistant",
        "red": 0.027, "green": 1.0, "blue": 1.0,   # cyan, as LVA sends it
    })
    await asyncio.sleep(0.15)
    r, g, b = ring.frames[-1][0]
    assert g > r and b > r, f"wheel colour not applied: {ring.frames[-1][0]}"

    # a state echo repeating the same effect must not snap back to purple
    await director.on_event("light_command", {
        "object_id": "led_ring", "state": True, "effect": "Voice Assistant",
        "red": 0.027, "green": 1.0, "blue": 1.0,
    })
    await asyncio.sleep(0.15)
    r2, g2, b2 = ring.frames[-1][0]
    assert g2 > r2 and b2 > r2, f"state echo reset the wheel colour: {(r2, g2, b2)}"

    # but selecting a preset does override it
    await director.on_event("light_command", {
        "object_id": "led_ring", "effect": "Green",
        "red": 0.027, "green": 1.0, "blue": 1.0,
    })
    await asyncio.sleep(0.15)
    r, g, b = ring.frames[-1][0]
    assert g > r and g > b, f"preset did not override the wheel: {(r, g, b)}"

    await director.on_event("tts_speaking", {})
    await asyncio.sleep(0.1)

    # --- commands for another entity are ignored ----------------------------
    await director.on_event("light_command", {"object_id": "somebody_else", "state": False})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'speaking', "took a command meant for another entity"

    # --- zeroconf is how LVA reports coming back ----------------------------
    await director.on_event("disconnected", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == "ha_down", runner.current
    await director.on_event("zeroconf", {"status": "connected"})
    await asyncio.sleep(0.05)
    assert runner.current.name != "ha_down", "zeroconf connected should clear the fault"

    await director.on_event("zeroconf", {"status": "disconnected"})
    await asyncio.sleep(0.05)
    assert runner.current.name == "ha_down", runner.current
    await director.on_event("zeroconf", {"status": "something else"})
    await asyncio.sleep(0.05)
    assert runner.current.name == "ha_down", "an unknown status should change nothing"
    await director.on_event("zeroconf", {"status": "connected"})
    await asyncio.sleep(0.05)

    # --- faults still show through the voice effect -------------------------
    await director.on_disconnected()
    await asyncio.sleep(0.05)
    assert runner.current.name == 'lva_down', runner.current

    await runner.close()
    print("OK — registration, off/lamp/voice modes, brightness, effects and routing pass")


if __name__ == "__main__":
    asyncio.run(main())
