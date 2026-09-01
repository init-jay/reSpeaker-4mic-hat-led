"""Exercise PeripheralClient against a stand-in for LVA's peripheral API.

Runs a WebSocket server that speaks the peripheral protocol, then checks the
client dispatches events, survives malformed messages, sends commands,
reconnects with growing backoff, and shuts down from an idle connection.

    uv run python tests/check_client.py
"""

import asyncio
import json
import logging

from websockets.asyncio.server import serve

from fakes import add_repo_to_path

add_repo_to_path()

from main import PeripheralClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")

PORT = 61234
received_commands = []
connection_count = 0


async def handler(ws):
    """Send a short pipeline, collect any command, then hang up."""
    global connection_count
    connection_count += 1
    me = connection_count

    await ws.send(json.dumps({"event": "snapshot", "data": {"muted": False, "volume": 0.4}}))
    for event in ("wake_word_detected", "listening", "thinking", "tts_speaking"):
        await ws.send(json.dumps({"event": event, "data": {}}))
    await ws.send(json.dumps({"event": "muted", "data": {"muted": True}}))
    await ws.send("this is not json")                      # malformed
    await ws.send(json.dumps({"nonsense": True}))          # wrong shape
    await ws.send(json.dumps({"event": "odd", "data": 7}))  # non-object data

    with_timeout = asyncio.get_running_loop().time() + 0.5
    while asyncio.get_running_loop().time() < with_timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.1)
        except asyncio.TimeoutError:
            break
        received_commands.append(json.loads(raw))

    if me == 1:
        await ws.close()  # force the client through its reconnect path


async def main():
    events = []

    async def on_event(event, data):
        events.append((event, data))

    disconnects = []

    async def on_disconnected():
        disconnects.append(True)

    async with serve(handler, "localhost", PORT):
        client = PeripheralClient(
            f"ws://localhost:{PORT}",
            on_event=on_event,
            on_disconnected=on_disconnected,
            initial_backoff=0.2,
        )
        task = asyncio.create_task(client.run())

        await asyncio.sleep(0.4)
        assert client.connected, "should be connected"
        assert await client.send_command("register_light", {"name": "Ring"}), "send failed"

        await asyncio.sleep(1.2)  # let it drop and reconnect

        # Idle-connection shutdown must not hang.
        client.stop()
        await asyncio.wait_for(task, timeout=2.0)

    names = [e for e, _ in events]
    assert names[0] == "snapshot", names[:1]
    assert "wake_word_detected" in names and "tts_speaking" in names, names
    assert ("muted", {"muted": True}) in events, events
    assert ("odd", {}) in events, "non-object data should be normalised to {}"
    assert not any(n in ("this is not json", "nonsense") for n in names)
    assert connection_count >= 2, f"expected a reconnect, got {connection_count}"
    assert disconnects, "on_disconnected never fired"
    assert received_commands == [{"command": "register_light", "data": {"name": "Ring"}}], received_commands

    # Short-lived connections must not reset the backoff: with stable_after=5s
    # and connections lasting well under that, 5 attempts in ~1.6s would be
    # impossible if the delay were growing 0.2 -> 0.4 -> 0.8 ... unless it had
    # been resetting. Verify the growth directly instead.
    slow = PeripheralClient("ws://localhost:1", initial_backoff=0.1, max_backoff=0.8)
    delays = []
    orig_wait = asyncio.wait_for

    async def spy(aw, timeout):
        delays.append(timeout)
        if len(delays) >= 4:
            slow.stop()
        return await orig_wait(aw, timeout=0.01)

    asyncio.wait_for = spy
    try:
        await slow.run()
    finally:
        asyncio.wait_for = orig_wait
    assert delays[:4] == [0.1, 0.2, 0.4, 0.8], delays

    # send_command with no connection reports failure rather than raising
    idle = PeripheralClient(f"ws://localhost:{PORT}")
    assert await idle.send_command("register_light") is False

    print(f"\nOK — {len(events)} events over {connection_count} connections, "
          f"{len(disconnects)} disconnect(s), clean shutdown")


if __name__ == "__main__":
    asyncio.run(main())
