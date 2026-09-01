"""Stand-ins for the hardware, so the checks run anywhere.

Nothing here talks to a Pi. `apa102.py` is the only module that touches SPI or
GPIO, and it is kept behind a lazy import in `main.py`, so the animations and
the event mapping can be exercised against :class:`FakeRing` on any machine.
"""

import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def add_repo_to_path() -> None:
    """Make the modules under test importable however the check was invoked."""
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


class FakeRing:
    """Stands in for APA102, recording every frame that gets shown.

    ``frames`` is the list of frames pushed by ``show()``, each a list of
    ``(red, green, blue)`` per pixel — which is what the checks assert against.
    """

    def __init__(self, num_leds: int = 12, global_brightness: int = 5) -> None:
        self.num_leds = num_leds
        self.global_brightness = global_brightness
        self._pixels = [(0, 0, 0)] * num_leds
        self.frames: list[list[tuple[int, int, int]]] = []

    def set_pixel(self, index, red, green, blue, brightness=None):
        if 0 <= index < self.num_leds:
            self._pixels[index] = (red, green, blue)

    def fill(self, red, green, blue, brightness=None):
        self._pixels = [(red, green, blue)] * self.num_leds

    def get_pixel(self, index):
        return self._pixels[index]

    def show(self):
        self.frames.append(list(self._pixels))

    def clear(self, show=True):
        self._pixels = [(0, 0, 0)] * self.num_leds
        if show:
            self.show()


class FakeSpiDev:
    """Captures the bytes apa102.py would put on the wire."""

    def __init__(self) -> None:
        self.max_speed_hz = None
        self.mode = None
        self.opened = None
        self.written: list[bytes] = []

    def open(self, bus, device):
        self.opened = (bus, device)

    def writebytes2(self, data):
        self.written.append(bytes(data))

    def close(self):
        pass


class FakeDigitalOutputDevice:
    """Records what apa102.py does with GPIO5."""

    def __init__(self, pin, initial_value=False) -> None:
        self.pin = pin
        self.value = initial_value

    def off(self):
        self.value = False

    def close(self):
        pass


def install_hardware_stubs() -> list[bytes]:
    """Fake out spidev and gpiozero, then return the shared write log.

    Must be called before importing ``apa102``. Every FakeSpiDev appends to the
    returned list, so frames from all instances arrive in one place.
    """
    written: list[bytes] = []

    class SharedSpiDev(FakeSpiDev):
        def writebytes2(self, data):
            written.append(bytes(data))

    spidev_stub = types.ModuleType("spidev")
    spidev_stub.SpiDev = SharedSpiDev
    gpiozero_stub = types.ModuleType("gpiozero")
    gpiozero_stub.DigitalOutputDevice = FakeDigitalOutputDevice

    sys.modules["spidev"] = spidev_stub
    sys.modules["gpiozero"] = gpiozero_stub
    return written
