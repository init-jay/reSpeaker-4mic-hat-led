"""Low-level control of the 12 APA102 LEDs on the ReSpeaker 4-Mic Array.

Protocol implemented from the APA102 datasheet framing documented in PLAN.md;
the structure follows wyoming-satellite's ``examples/4mic_leds.py``, which in
turn derives from Seeed's ``apa102.py``.

Two things about this board specifically:

* GPIO5 gates VCC to the LED ring. Until it is driven HIGH the LEDs are
  unpowered and correct SPI writes do nothing at all.
* SPI is provided by the ``seeed-4mic-voicecard`` overlay, so ``/dev/spidev0.0``
  exists without ``dtparam=spi=on`` in ``config.txt``.
"""

from __future__ import annotations

import time
from typing import Optional

import spidev
from gpiozero import DigitalOutputDevice

NUM_LEDS = 12
POWER_GPIO = 5
MAX_BRIGHTNESS = 31

# 4 bytes of zero open a frame; the per-LED header is 0xE0 | 5-bit brightness.
START_FRAME = b"\x00\x00\x00\x00"
LED_HEADER = 0xE0

_BYTES_PER_LED = 4


class APA102:
    """An APA102 LED strip on SPI, with the ring's power rail under our control.

    Pixel values are staged in a local buffer by :meth:`set_pixel` and only
    reach the strip when :meth:`show` is called.
    """

    def __init__(
        self,
        num_leds: int = NUM_LEDS,
        *,
        bus: int = 0,
        device: int = 0,
        max_speed_hz: int = 8_000_000,
        global_brightness: int = 15,
        power_gpio: Optional[int] = POWER_GPIO,
    ) -> None:
        self.num_leds = num_leds
        self.global_brightness = _clamp(global_brightness, 1, MAX_BRIGHTNESS)
        self._buf = bytearray(_BYTES_PER_LED * num_leds)

        # The end frame needs at least num_leds/2 clock bits to push the last
        # pixel down the chain — num_leds/16 bytes, and never fewer than 4.
        self._end_frame = b"\xff" * max(4, (num_leds + 15) // 16)

        # Held as an attribute for its whole lifetime: gpiozero releases the pin
        # when the device is garbage collected, which would cut power to the ring.
        self._power = (
            DigitalOutputDevice(power_gpio, initial_value=True)
            if power_gpio is not None
            else None
        )
        if self._power is not None:
            time.sleep(0.05)  # let the rail come up before clocking data in

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = max_speed_hz
        self._spi.mode = 0b00

        self.clear()

    def set_pixel(
        self,
        index: int,
        red: int,
        green: int,
        blue: int,
        brightness: Optional[int] = None,
    ) -> None:
        """Stage one pixel. Colours are 0-255, ``brightness`` 0-31.

        ``brightness`` defaults to :attr:`global_brightness`. Out-of-range
        indices are ignored so animations can walk off the end of the ring
        without special-casing.
        """
        if not 0 <= index < self.num_leds:
            return

        level = self.global_brightness if brightness is None else brightness
        offset = index * _BYTES_PER_LED

        self._buf[offset] = LED_HEADER | _clamp(level, 0, MAX_BRIGHTNESS)
        # Byte order on the wire is blue, green, red — not RGB.
        self._buf[offset + 1] = _clamp(blue, 0, 255)
        self._buf[offset + 2] = _clamp(green, 0, 255)
        self._buf[offset + 3] = _clamp(red, 0, 255)

    def fill(
        self,
        red: int,
        green: int,
        blue: int,
        brightness: Optional[int] = None,
    ) -> None:
        """Stage the same colour on every pixel."""
        for index in range(self.num_leds):
            self.set_pixel(index, red, green, blue, brightness)

    def show(self) -> None:
        """Write the staged buffer out to the strip."""
        self._spi.writebytes2(START_FRAME + bytes(self._buf) + self._end_frame)

    def clear(self, show: bool = True) -> None:
        """Blank every pixel, writing immediately unless ``show`` is False."""
        for index in range(self.num_leds):
            self.set_pixel(index, 0, 0, 0, brightness=0)
        if show:
            self.show()

    def close(self) -> None:
        """Blank the ring, then release SPI and the power pin."""
        try:
            self.clear()
        finally:
            self._spi.close()
            if self._power is not None:
                self._power.off()
                self._power.close()
                self._power = None

    def __enter__(self) -> "APA102":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, int(value)))
