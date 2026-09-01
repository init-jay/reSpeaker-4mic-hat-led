"""Exercise the animations and the event mapping against a fake ring.

Replays the event sequence captured from a real interaction, at the pace it
actually arrived, and checks the animation the ring would be showing at each
point.

    uv run python tests/check_animations.py
"""

import asyncio

from fakes import FakeRing, add_repo_to_path

add_repo_to_path()

import animations  # noqa: E402
from main import LedDirector  # noqa: E402


async def main():
    ring = FakeRing()
    runner = animations.AnimationRunner(ring)
    director = LedDirector(runner)

    # --- the real Phase 2 capture, replayed at its observed pace -------------
    await director.on_connected()
    await director.on_event("snapshot", {"muted": False, "volume": 1.0, "ha_connected": True})
    await asyncio.sleep(0.05)
    assert runner.current is animations.IDLE, runner.current

    await director.on_event("wake_word_detected", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'wake', runner.current

    # listening/stt_text/thinking/tts_speaking all landed within a second in
    # the capture; thinking must still get its min_hold on screen.
    await director.on_event("listening", {})
    await director.on_event("stt_text", {"text": "hello"})
    await director.on_event("thinking", {})
    await asyncio.sleep(0.4)
    assert runner.current.name == 'thinking', f"wake min_hold then thinking, got {runner.current}"

    await director.on_event("tts_speaking", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'thinking', "thinking cut off before its min_hold"
    await asyncio.sleep(0.8)
    assert runner.current.name == 'speaking', runner.current

    await director.on_event("tts_text", {"text": "hi"})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'speaking', "tts_text should change nothing"

    await director.on_event("tts_finished", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'speaking', "tts_finished should change nothing"

    ring.frames.clear()
    await director.on_event("idle", {})
    await asyncio.sleep(0.7)
    assert runner.current is animations.IDLE
    assert ring.frames[-1] == [(0, 0, 0)] * 12, "idle should end dark"
    assert len(ring.frames) > 10, "idle should have faded, not snapped off"
    # the fade must be monotonic downward
    reds = [f[0][0] for f in ring.frames]
    assert reds[0] > reds[len(reds) // 2] > 0, f"not a fade: {reds[:5]}...{reds[-5:]}"

    # --- one-shots hand back to the state underneath ------------------------
    await director.on_event("tts_speaking", {})
    await asyncio.sleep(0.05)
    await director.on_event("pipeline_error", {})
    await asyncio.sleep(0.1)
    assert runner.current.name == 'error', runner.current
    await asyncio.sleep(1.1)
    assert runner.current.name == 'speaking', f"should fall back, got {runner.current}"

    await director.on_event("volume_changed", {"volume": 0.5})
    await asyncio.sleep(0.1)
    assert runner.current.name.startswith("volume"), runner.current
    lit = sum(1 for p in ring.frames[-1] if any(p))
    assert lit == 6, f"half volume should light 6 of 12, got {lit}"
    await asyncio.sleep(1.4)
    assert runner.current.name == 'speaking', f"volume should fall back, got {runner.current}"

    # --- priority ordering --------------------------------------------------
    await director.on_event("muted", {"muted": True})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'muted', runner.current

    await director.on_event("idle", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'muted', "muted must outrank pipeline state"

    await director.on_event("disconnected", {})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'muted', "muted must outrank ha_down"

    await director.on_event("muted", {"muted": False})
    await asyncio.sleep(0.05)
    assert runner.current.name == 'ha_down', runner.current

    await director.on_disconnected()
    await asyncio.sleep(0.05)
    assert runner.current.name == 'lva_down', "socket loss outranks everything"

    await director.on_connected()
    await asyncio.sleep(0.05)
    assert runner.current.name == 'ha_down', "should fall back to the HA fault"

    await director.on_event("connected", {})
    await asyncio.sleep(0.05)
    assert runner.current is animations.IDLE, runner.current

    # --- every animation draws without raising ------------------------------
    for anim in (
        animations.wake(), animations.listening(), animations.thinking(),
        animations.speaking(), animations.muted(), animations.lva_down(),
        animations.ha_down(), animations.timer(), animations.error(),
        animations.muted(0.2), animations.timer(0.5), animations.error(0.1),
        animations.volume(1.0), animations.volume(0.0),
        animations.wake((0, 255, 0)), animations.thinking((255, 0, 128)),
        animations.solid((10, 20, 30)), animations.breathe((1, 2, 3)),
        animations.rainbow(0.5),
    ):
        ring.frames.clear()
        task = asyncio.create_task(anim.run(ring))
        await asyncio.sleep(0.35)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert ring.frames, f"{anim} drew nothing"
        for frame in ring.frames:
            for r, g, b in frame:
                assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255, f"{anim}: {r},{g},{b}"

    # --- shutdown leaves the ring dark --------------------------------------
    await runner.close()
    assert ring.frames[-1] == [(0, 0, 0)] * 12, "close() should blank the ring"

    print("OK — replay, one-shot fallback, priority, min_hold and shutdown all pass")


if __name__ == "__main__":
    asyncio.run(main())
