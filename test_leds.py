#!/usr/bin/env python3
"""Phase 1 hardware check for the ReSpeaker 4-Mic Array LED ring.

Run directly on the Pi:

    python3 test_leds.py

Expected, in order:

1. All 12 LEDs solid red, then green, then blue, then off.
2. A single white pixel walking once around the ring, LED 0 first.
3. All 12 white, ramping brightness 1 -> 31 and back down.

Check for: correct colours (a red/blue swap means the byte order is wrong),
one continuous rotation with no gaps or doubles, and a smooth ramp with no
flicker at low brightness.
"""

import argparse
import sys
import time

from apa102 import MAX_BRIGHTNESS, NUM_LEDS, APA102

COLOURS = [
    ("red", (255, 0, 0)),
    ("green", (0, 255, 0)),
    ("blue", (0, 0, 255)),
    ("off", (0, 0, 0)),
]


def solid_cycle(leds: APA102, hold: float) -> None:
    for name, (red, green, blue) in COLOURS:
        print(f"  all {name}")
        leds.fill(red, green, blue)
        leds.show()
        time.sleep(hold)


def chase(leds: APA102, step: float) -> None:
    for index in range(leds.num_leds):
        print(f"  led {index}")
        leds.clear(show=False)
        leds.set_pixel(index, 255, 255, 255)
        leds.show()
        time.sleep(step)
    leds.clear()


def brightness_ramp(leds: APA102, step: float) -> None:
    levels = list(range(1, MAX_BRIGHTNESS + 1))
    for level in levels + levels[::-1]:
        leds.fill(255, 255, 255, brightness=level)
        leds.show()
        time.sleep(step)
    leds.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-leds", type=int, default=NUM_LEDS)
    parser.add_argument(
        "--brightness",
        type=int,
        default=15,
        help=f"global brightness, 1-{MAX_BRIGHTNESS} (default: %(default)s)",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=1.0,
        help="seconds to hold each solid colour (default: %(default)s)",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=0.08,
        help="seconds per chase / ramp step (default: %(default)s)",
    )
    args = parser.parse_args()

    print(f"opening {args.num_leds} LEDs at brightness {args.brightness}")
    with APA102(args.num_leds, global_brightness=args.brightness) as leds:
        try:
            print("solid colours")
            solid_cycle(leds, args.hold)
            print("chase")
            chase(leds, args.step)
            print("brightness ramp")
            brightness_ramp(leds, args.step)
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130

    print("done — ring is off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
