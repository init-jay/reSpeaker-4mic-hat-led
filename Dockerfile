# Everything comes from apt as a prebuilt package: lgpio and spidev both build
# C from PyPI, and lgpio additionally wants SWIG and the lgpio C library, which
# is a lot of toolchain to carry into an image for one GPIO pin and one SPI
# device. Nothing here needs a compiler.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-gpiozero \
        python3-lgpio \
        python3-spidev \
        python3-websockets \
    && rm -rf /var/lib/apt/lists/*

# lgpio is the working pin factory on current Raspberry Pi kernels; naming it
# explicitly stops gpiozero probing for others and failing noisily first.
ENV GPIOZERO_PIN_FACTORY=lgpio \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY apa102.py animations.py main.py ./

# SIGTERM is handled: the ring is blanked and the socket closed on the way out.
STOPSIGNAL SIGTERM

ENTRYPOINT ["python3", "main.py"]
