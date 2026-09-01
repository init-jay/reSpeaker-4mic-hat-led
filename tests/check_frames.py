"""Verify APA102 frame construction with spidev/gpiozero stubbed out.

This is the one check that exercises the hardware module, by faking the two
libraries it imports. It asserts the bytes that would reach the strip: the
frame layout, the per-LED byte order, and that GPIO5 is driven high.

    uv run python tests/check_frames.py
"""

from fakes import add_repo_to_path, install_hardware_stubs

add_repo_to_path()
written = install_hardware_stubs()

from apa102 import APA102  # noqa: E402

leds = APA102(12, global_brightness=15)
assert leds._power.pin == 5 and leds._power.value is True, "GPIO5 not driven high"
assert leds._spi.max_speed_hz == 8_000_000 and leds._spi.mode == 0

# clear() ran in __init__ -> one frame of all-zero pixels
frame = written[-1]
assert len(frame) == 4 + 12 * 4 + 4, f"bad frame length {len(frame)}"
assert frame[:4] == b"\x00\x00\x00\x00", "bad start frame"
assert frame[-4:] == b"\xff\xff\xff\xff", "bad end frame"
assert frame[4:-4] == bytes([0xE0, 0, 0, 0] * 12), "clear() should zero everything"

written.clear()
leds.set_pixel(0, 255, 0, 0)          # red, global brightness
leds.set_pixel(1, 0, 128, 0, 31)      # green, explicit brightness
leds.set_pixel(11, 0, 0, 64)          # blue, last LED
leds.set_pixel(12, 255, 255, 255)     # out of range -> ignored
leds.set_pixel(-1, 255, 255, 255)     # out of range -> ignored
leds.show()

body = written[-1][4:-4]
px = lambda i: list(body[i * 4 : i * 4 + 4])  # noqa: E731
assert px(0) == [0xE0 | 15, 0, 0, 255], f"LED0 wrong: {px(0)}"   # hdr, B, G, R
assert px(1) == [0xE0 | 31, 0, 128, 0], f"LED1 wrong: {px(1)}"
assert px(11) == [0xE0 | 15, 64, 0, 0], f"LED11 wrong: {px(11)}"
assert px(2) == [0xE0, 0, 0, 0], "untouched pixel changed"  # still blank from clear()

# clamping
leds.set_pixel(0, 999, -5, 0, brightness=99)
leds.show()
assert list(written[-1][4:8]) == [0xE0 | 31, 0, 0, 255], "clamping failed"

# end frame scales for longer strips: 144 LEDs -> 9 bytes
assert APA102(144)._end_frame == b"\xff" * 9

# fill + close
leds.fill(10, 20, 30)
leds.show()
assert list(written[-1][4:8]) == [0xE0 | 15, 30, 20, 10], "fill order wrong"
leds.close()
assert written[-1][4:-4] == bytes([0xE0, 0, 0, 0] * 12), "close() should blank"

# global_brightness reaches the wire, and animations inherit it by passing
# brightness=None -- this is what the HA slider ends up controlling
leds2 = APA102(12, global_brightness=15)
written.clear()
leds2.set_pixel(0, 255, 0, 0)
leds2.show()
assert written[-1][4] == (0xE0 | 15), hex(written[-1][4])
leds2.global_brightness = 3
leds2.set_pixel(0, 255, 0, 0)
leds2.show()
assert written[-1][4] == (0xE0 | 3), "global_brightness change did not reach the frame"
leds2.fill(255, 255, 255)
leds2.show()
assert written[-1][4] == (0xE0 | 3), "fill should inherit global_brightness too"

print("all frame checks passed")
