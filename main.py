#!/usr/bin/env python3
"""WebSocket client for the Linux Voice Assistant peripheral API.

Phase 2: connect, log every event, survive LVA restarts. Animations are wired
in at Phase 3 through the ``on_event`` / ``on_disconnected`` callbacks.

Run it directly to watch the event stream:

    uv run python main.py --record events.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, TextIO

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

import animations

DEFAULT_URI = "ws://localhost:6055"

_LOGGER = logging.getLogger("lva-leds")

EventHandler = Callable[[str, dict[str, Any]], Awaitable[None]]
StateHandler = Callable[[], Awaitable[None]]


class PeripheralClient:
    """Maintains a connection to LVA's peripheral API.

    :meth:`run` never returns until :meth:`stop` is called — a dropped
    connection means LVA is down, which is a state to display rather than an
    error to exit on.
    """

    def __init__(
        self,
        uri: str = DEFAULT_URI,
        *,
        on_event: Optional[EventHandler] = None,
        on_connected: Optional[StateHandler] = None,
        on_disconnected: Optional[StateHandler] = None,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
        stable_after: float = 5.0,
    ) -> None:
        self.uri = uri
        self._on_event = on_event
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._stable_after = stable_after

        self._ws: Optional[Any] = None
        self._stop = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def run(self) -> None:
        """Connect, dispatch messages, and reconnect with backoff until stopped."""
        loop = asyncio.get_running_loop()
        delay = self._initial_backoff
        connected_at = 0.0

        while not self._stop.is_set():
            try:
                async with connect(self.uri, open_timeout=5) as ws:
                    self._ws = ws
                    connected_at = loop.time()
                    _LOGGER.info("connected to %s", self.uri)
                    if self._on_connected is not None:
                        await self._on_connected()

                    async for raw in ws:
                        await self._handle_message(raw)

                if not self._stop.is_set():
                    _LOGGER.warning("connection closed by LVA")
            except asyncio.CancelledError:
                raise
            except (OSError, ConnectionClosed, InvalidHandshake, TimeoutError) as err:
                _LOGGER.warning("connection failed: %s", err)
            finally:
                was_connected = self._ws is not None
                self._ws = None
                if was_connected and self._on_disconnected is not None:
                    await self._on_disconnected()

            if self._stop.is_set():
                break

            # Only a connection that stayed up earns a reset, otherwise an LVA
            # crash-looping on startup would be hammered once a second forever.
            if was_connected and loop.time() - connected_at >= self._stable_after:
                delay = self._initial_backoff

            _LOGGER.info("reconnecting in %.1fs", delay)
            # Wake early if we are asked to stop while waiting.
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            delay = min(delay * 2, self._max_backoff)

    def stop(self) -> None:
        """Ask :meth:`run` to return at the next opportunity."""
        self._stop.set()

        # Without this an idle connection would sit in `async for` until the
        # next event arrived, so SIGTERM would appear to hang.
        ws = self._ws
        if ws is not None:
            with suppress(RuntimeError):
                asyncio.get_running_loop().create_task(ws.close())

    async def send_command(self, command: str, data: Optional[dict] = None) -> bool:
        """Send a command to LVA. Returns False if there is no connection.

        Used from Phase 4 for ``register_light``.
        """
        if self._ws is None:
            _LOGGER.warning("cannot send %r: not connected", command)
            return False

        payload = {"command": command, "data": data or {}}
        try:
            await self._ws.send(json.dumps(payload))
        except (ConnectionClosed, OSError) as err:
            _LOGGER.warning("failed to send %r: %s", command, err)
            return False

        _LOGGER.debug("sent %s", payload)
        return True

    async def _handle_message(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.warning("ignoring non-JSON message: %r", raw[:200])
            return

        if not isinstance(message, dict) or "event" not in message:
            _LOGGER.warning("ignoring unexpected message shape: %r", message)
            return

        event = message["event"]
        data = message.get("data") or {}
        if not isinstance(data, dict):
            _LOGGER.warning("event %r has non-object data: %r", event, data)
            data = {}

        if data:
            _LOGGER.info("event %s %s", event, data)
        else:
            _LOGGER.info("event %s", event)

        if self._on_event is not None:
            try:
                await self._on_event(event, data)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A broken animation must not take the connection down with it.
                _LOGGER.exception("handler failed for event %r", event)


class LedDirector:
    """Maps peripheral events onto ring animations.

    Pipeline state is only what shows when nothing more important is wrong.
    Priority, highest first: our socket to LVA is down, muted, LVA cannot reach
    Home Assistant, then the pipeline itself. The two connectivity faults are
    genuinely different — LVA being gone is not the same as LVA being up but
    unable to reach HA — so they get different animations.
    """

    _PIPELINE = {
        "wake_word_detected": animations.WAKE,
        "listening": animations.LISTENING,
        "thinking": animations.THINKING,
        "tts_speaking": animations.SPEAKING,
        "idle": animations.IDLE,
        "timer_ringing": animations.TIMER,
    }

    # tts_finished is deliberately absent: idle follows it immediately and
    # carries the fade. stt_text/tts_text are text only, nothing to show.
    _IGNORED = {"tts_finished", "stt_text", "tts_text"}

    def __init__(self, runner: animations.AnimationRunner) -> None:
        self._runner = runner
        self._pipeline = animations.IDLE
        self._muted = False
        self._ha_connected = True
        self._lva_connected = True

    async def on_event(self, event: str, data: dict[str, Any]) -> None:
        if event == "snapshot":
            self._muted = bool(data.get("muted", False))
            self._ha_connected = bool(data.get("ha_connected", True))
        elif event == "muted":
            self._muted = bool(data.get("muted", True))
        elif event == "connected":
            self._ha_connected = True
        elif event == "disconnected":
            self._ha_connected = False
        elif event == "pipeline_error":
            self._runner.flash(animations.ERROR)
            return
        elif event == "volume_changed":
            volume = data.get("volume")
            if isinstance(volume, (int, float)):
                self._runner.flash(animations.volume(float(volume)))
            return
        elif event in self._IGNORED:
            return
        elif event in self._PIPELINE:
            self._pipeline = self._PIPELINE[event]
        else:
            _LOGGER.debug("no animation for event %r", event)
            return

        self._refresh()

    async def on_connected(self) -> None:
        self._lva_connected = True
        self._refresh()

    async def on_disconnected(self) -> None:
        self._lva_connected = False
        self._refresh()

    def _refresh(self) -> None:
        if not self._lva_connected:
            state = animations.LVA_DOWN
        elif self._muted:
            state = animations.MUTED
        elif not self._ha_connected:
            state = animations.HA_DOWN
        else:
            state = self._pipeline

        self._runner.set_state(state)


class EventRecorder:
    """Appends every event to a JSONL file for offline inspection."""

    def __init__(self, path: Path) -> None:
        self._file: TextIO = path.open("a", encoding="utf-8")

    async def __call__(self, event: str, data: dict[str, Any]) -> None:
        line = {
            "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            "data": data,
        }
        self._file.write(json.dumps(line) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


async def _amain(args: argparse.Namespace) -> int:
    recorder = EventRecorder(args.record) if args.record else None

    leds = None
    runner = None
    director = None
    if not args.no_leds:
        # Imported here so the client still runs on a machine without the
        # hardware — useful for reading the event stream from a laptop.
        from apa102 import APA102

        leds = APA102(args.num_leds, global_brightness=args.brightness)
        runner = animations.AnimationRunner(leds)
        director = LedDirector(runner)

    async def on_event(event: str, data: dict[str, Any]) -> None:
        if event == "snapshot":
            _LOGGER.info("initial state: %s", data or "(empty)")
        if recorder is not None:
            await recorder(event, data)
        if director is not None:
            await director.on_event(event, data)

    async def on_connected() -> None:
        if director is not None:
            await director.on_connected()

    async def on_disconnected() -> None:
        _LOGGER.warning("disconnected from LVA")
        if director is not None:
            await director.on_disconnected()

    client = PeripheralClient(
        args.uri,
        on_event=on_event,
        on_connected=on_connected,
        on_disconnected=on_disconnected,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, client.stop)

    try:
        await client.run()
    finally:
        if runner is not None:
            await runner.close()
        if leds is not None:
            leds.close()
        if recorder is not None:
            recorder.close()

    _LOGGER.info("stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default=DEFAULT_URI, help="default: %(default)s")
    parser.add_argument(
        "--record",
        type=Path,
        metavar="PATH",
        help="append every event to this file as JSONL",
    )
    parser.add_argument(
        "--brightness",
        type=int,
        default=5,
        help="ring brightness ceiling, 1-31 (default: %(default)s)",
    )
    parser.add_argument("--num-leds", type=int, default=12)
    parser.add_argument(
        "--no-leds",
        action="store_true",
        help="log events only, do not touch the hardware",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log raw traffic")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        return asyncio.run(_amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
