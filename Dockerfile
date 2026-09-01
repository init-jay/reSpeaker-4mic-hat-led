# Everything comes from Debian as a prebuilt package, so the image carries no
# compiler and no pip.
#
# Note what is *not* here: lgpio, the pin factory used on the host. It is a
# Raspberry Pi OS package rather than a Debian one, and adding that archive
# means trusting a key whose self-signature is SHA1, which trixie's verifier
# rejects outright. Since all we need from GPIO is to hold one pin high,
# gpiozero's own native factory does the job with no dependency at all.
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-gpiozero \
        python3-spidev \
        python3-websockets \
    && rm -rf /var/lib/apt/lists/*

# The native factory is pure Python and drives the pins by mapping
# /dev/gpiomem, so it needs that device rather than /dev/gpiochip0. Naming it
# explicitly stops gpiozero probing for lgpio and friends first.
ENV GPIOZERO_PIN_FACTORY=native \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY apa102.py animations.py main.py ./

# SIGTERM is handled: the ring is blanked and the socket closed on the way out.
STOPSIGNAL SIGTERM

ENTRYPOINT ["python3", "main.py"]
