"""Named, cancellable animations for the 12-LED ring.

An :class:`Animation` is a name plus a coroutine that draws frames until it is
cancelled. :class:`AnimationRunner` keeps exactly one running, swapping it out
as pipeline state changes.

Two things the Phase 2 capture forced on this design:

* ``thinking`` can last under a second, so an animation carries a ``min_hold``
  and the runner will not cut it off before that has elapsed.
* ``tts_speaking`` carries no duration, so playback animations free-run until
  something replaces them rather than being timed.

Colour is scaled in RGB rather than through the APA102's 5-bit brightness
field, which is far too coarse to fade smoothly. The brightness field stays at
whatever ceiling the ring was opened with.

Nothing here imports the hardware, so the animations can be exercised against a
stand-in on a development machine.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

if TYPE_CHECKING:
    from apa102 import APA102

FRAME = 1 / 50  # seconds between frames

Color = tuple[int, int, int]

RED: Color = (255, 0, 0)
AMBER: Color = (255, 110, 0)
BLUE: Color = (40, 120, 255)
# Weighted away from pure magenta so it still reads as purple once dimmed.
PURPLE: Color = (150, 20, 255)

_LOGGER = logging.getLogger("lva-leds.animations")


def scale(color: Color, factor: float) -> Color:
    """Dim ``color`` by ``factor`` (0.0-1.0)."""
    f = max(0.0, min(1.0, factor))
    return (int(color[0] * f), int(color[1] * f), int(color[2] * f))


@dataclass(frozen=True)
class Animation:
    """A named frame loop.

    ``run`` is cancelled when the animation is replaced. ``min_hold`` is the
    shortest time it should stay on screen once started, so that states LVA
    passes through in milliseconds are still visible.
    """

    name: str
    run: Callable[["APA102"], Awaitable[None]]
    min_hold: float = 0.0

    def __str__(self) -> str:
        return self.name


async def _forever() -> None:
    """Park until cancelled, leaving the ring as drawn."""
    await asyncio.Event().wait()


async def _ramp(leds: "APA102", color: Color, start: float, end: float, seconds: float) -> None:
    """Fill the ring, sweeping its level from ``start`` to ``end``."""
    steps = max(1, int(seconds / FRAME))
    for step in range(steps + 1):
        level = start + (end - start) * (step / steps)
        leds.fill(*scale(color, level))
        leds.show()
        await asyncio.sleep(FRAME)


async def _pulse(leds: "APA102", color: Color, low: float, high: float, period: float) -> None:
    """Breathe between two levels, forever."""
    elapsed = 0.0
    while True:
        # Cosine gives a softer turnaround at the extremes than a triangle wave.
        phase = (1 - math.cos(2 * math.pi * elapsed / period)) / 2
        leds.fill(*scale(color, low + (high - low) * phase))
        leds.show()
        elapsed += FRAME
        await asyncio.sleep(FRAME)


async def _twinkle(leds: "APA102", color: Color, level: float) -> None:
    """Random pixels flicker — used for the two 'something is down' states."""
    while True:
        for index in range(leds.num_leds):
            leds.set_pixel(index, *scale(color, random.uniform(0.0, level)))
        leds.show()
        await asyncio.sleep(0.09)


async def _idle(leds: "APA102") -> None:
    """Fade out whatever is showing, then stay dark.

    ``tts_finished`` and ``idle`` arrive together, so the fade lives here
    rather than being a separate animation that would be cut off immediately.
    """
    start = [leds.get_pixel(i) for i in range(leds.num_leds)]
    if any(any(pixel) for pixel in start):
        steps = int(0.5 / FRAME)
        for step in range(steps, -1, -1):
            level = step / steps
            for index, pixel in enumerate(start):
                leds.set_pixel(index, *scale(pixel, level))
            leds.show()
            await asyncio.sleep(FRAME)

    leds.clear()
    await _forever()


async def _wake(leds: "APA102") -> None:
    """Red flash on the full ring, settling to a steady purple."""
    await _ramp(leds, RED, 0.0, 1.0, 0.06)
    await _ramp(leds, RED, 1.0, 0.25, 0.20)
    await _ramp(leds, PURPLE, 0.25, 0.45, 0.10)
    await _forever()


async def _listening(leds: "APA102") -> None:
    await _pulse(leds, BLUE, 0.15, 0.65, period=2.5)


async def _thinking(leds: "APA102") -> None:
    """A comet with a fading tail, one revolution every 0.9s."""
    tail = 0.55
    position = 0.0
    while True:
        head = int(position) % leds.num_leds
        for index in range(leds.num_leds):
            distance = (head - index) % leds.num_leds
            leds.set_pixel(index, *scale(BLUE, tail**distance))
        leds.show()
        position += leds.num_leds * FRAME / 0.9
        await asyncio.sleep(FRAME)


async def _speaking(leds: "APA102") -> None:
    """Free-running pulse: nothing tells us how long playback lasts."""
    await _pulse(leds, PURPLE, 0.2, 0.9, period=0.9)


async def _muted(leds: "APA102") -> None:
    leds.fill(*scale(RED, 0.5))
    leds.show()
    await _forever()


async def _lva_down(leds: "APA102") -> None:
    """Our own socket to LVA is gone."""
    await _twinkle(leds, RED, 0.7)


async def _ha_down(leds: "APA102") -> None:
    """LVA is up but is not talking to Home Assistant — a different fault."""
    await _twinkle(leds, AMBER, 0.6)


async def _timer(leds: "APA102") -> None:
    """Alternating halves, fast enough to demand attention."""
    on = True
    while True:
        for index in range(leds.num_leds):
            lit = (index < leds.num_leds // 2) == on
            leds.set_pixel(index, *(AMBER if lit else (0, 0, 0)))
        leds.show()
        on = not on
        await asyncio.sleep(0.25)


async def _error(leds: "APA102") -> None:
    """Three red flashes, then hand back to whatever state is current."""
    for _ in range(3):
        leds.fill(*RED)
        leds.show()
        await asyncio.sleep(0.12)
        leds.clear()
        await asyncio.sleep(0.12)


IDLE = Animation("idle", _idle)
WAKE = Animation("wake", _wake, min_hold=0.3)
LISTENING = Animation("listening", _listening)
THINKING = Animation("thinking", _thinking, min_hold=0.7)
SPEAKING = Animation("speaking", _speaking)
MUTED = Animation("muted", _muted)
LVA_DOWN = Animation("lva_down", _lva_down)
HA_DOWN = Animation("ha_down", _ha_down)
TIMER = Animation("timer", _timer)
ERROR = Animation("error", _error, min_hold=0.75)


def volume(level: float) -> Animation:
    """A one-shot bar showing ``level`` (0.0-1.0) around the ring."""

    async def run(leds: "APA102") -> None:
        lit = round(max(0.0, min(1.0, level)) * leds.num_leds)
        for index in range(leds.num_leds):
            leds.set_pixel(index, *(scale(PURPLE, 0.6) if index < lit else (0, 0, 0)))
        leds.show()
        await asyncio.sleep(1.0)

    return Animation(f"volume({level:.2f})", run, min_hold=0.5)


class AnimationRunner:
    """Runs one animation at a time, swapping as state changes.

    :meth:`set_state` sets the animation to rest in. :meth:`flash` overlays a
    one-shot that hands back to that state when it finishes. Both return
    immediately — waiting out a ``min_hold`` happens on a background task so
    the WebSocket is never blocked by the LEDs.
    """

    def __init__(self, leds: "APA102") -> None:
        self._leds = leds
        self._base: Animation = IDLE
        self._transient: Optional[Animation] = None
        self._current: Optional[Animation] = None
        self._started = 0.0
        self._task: Optional[asyncio.Task] = None
        self._switch: Optional[asyncio.Task] = None
        self._closed = False

    @property
    def current(self) -> Optional[Animation]:
        return self._current

    def set_state(self, animation: Animation) -> None:
        # No early return when this already matches the base: at startup the
        # base is IDLE and nothing is running yet, so that would leave the ring
        # dead until the first state change. _apply is what decides whether a
        # switch is actually needed.
        self._base = animation
        self._request()

    def flash(self, animation: Animation) -> None:
        self._transient = animation
        self._request()

    def _request(self) -> None:
        if self._closed:
            return
        if self._switch is not None:
            self._switch.cancel()
        self._switch = asyncio.create_task(self._apply())

    async def _apply(self) -> None:
        target = self._transient or self._base
        if target is self._current:
            return

        loop = asyncio.get_running_loop()
        if self._current is not None:
            remaining = self._current.min_hold - (loop.time() - self._started)
            if remaining > 0:
                await asyncio.sleep(remaining)
                # State may have moved on again while we were holding.
                target = self._transient or self._base
                if target is self._current:
                    return

        await self._cancel_running()
        _LOGGER.debug("animation -> %s", target)
        self._current = target
        self._started = loop.time()
        self._task = asyncio.create_task(self._run(target))

    async def _run(self, animation: Animation) -> None:
        try:
            await animation.run(self._leds)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("animation %s failed", animation)

        # Ran to completion: a one-shot is done, so fall back to the base state.
        if self._transient is animation:
            self._transient = None
            self._request()

    async def _cancel_running(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def close(self) -> None:
        """Stop animating and leave the ring dark."""
        self._closed = True
        if self._switch is not None:
            self._switch.cancel()
            with suppress(asyncio.CancelledError):
                await self._switch
        await self._cancel_running()
        self._current = None
        self._leds.clear()
