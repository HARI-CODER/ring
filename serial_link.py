"""Forward ring events from the bridge to an Arduino over USB serial.

    python bridge.py           # terminal 1
    python serial_link.py      # terminal 2

    python serial_link.py --list                 # show candidate ports
    python serial_link.py --port /dev/cu.usbmodem14201
    python serial_link.py --echo                 # also print what the board says

Line protocol, newline-terminated ASCII in both directions:

    ->  G:<name>       a gesture was recognised
    ->  HR:<bpm>       heart rate reading
    ->  STEPS:<count>  step total
    ->  PING           keepalive every 5s, so the board can detect a dead link
    <-  anything       echoed to the console with --echo

Keep it line-based and human-readable: you can drive the board by hand from the
Arduino Serial Monitor, which makes debugging enormously easier than a binary
protocol.
"""

import argparse
import asyncio
import json
import sys
import time

import serial
import serial.tools.list_ports
import websockets

WS_URL = "ws://127.0.0.1:8765"
BAUD = 115200
# Most Arduinos reset when the port opens; nothing sent before the bootloader
# finishes is seen by the sketch.
RESET_SETTLE_SECONDS = 2.0
# Ignore repeats of the same gesture inside this window. Recognition can fire
# twice off one physical motion, and a board driving a relay should not see two.
GESTURE_COOLDOWN = 1.5
PING_SECONDS = 5.0
# A gesture older than this is history, not a command — see pump_ring().
STALE_SECONDS = 3.0

# USB-serial adapters seen on Arduino and clone boards.
PORT_HINTS = ("usbmodem", "usbserial", "wchusbserial", "SLAB_USBtoUART", "ttyACM", "ttyUSB")


def candidates() -> list:
    return [
        port
        for port in serial.tools.list_ports.comports()
        if any(hint.lower() in port.device.lower() for hint in PORT_HINTS)
    ]


def list_ports() -> None:
    everything = list(serial.tools.list_ports.comports())
    if not everything:
        print("No serial ports at all.")
        return
    likely = {port.device for port in candidates()}
    print("Serial ports (* = looks like an Arduino):")
    for port in everything:
        mark = "*" if port.device in likely else " "
        print(f" {mark} {port.device:<32} {port.description}")


def open_port(explicit: str | None) -> serial.Serial | None:
    if explicit:
        device = explicit
    else:
        found = candidates()
        if not found:
            return None
        device = found[0].device
        print(f"[serial] auto-detected {device}")

    try:
        link = serial.Serial(device, BAUD, timeout=0)
    except serial.SerialException as error:
        print(f"[serial] cannot open {device}: {error}")
        return None

    print(f"[serial] opened {device} at {BAUD}; waiting {RESET_SETTLE_SECONDS}s for board reset")
    time.sleep(RESET_SETTLE_SECONDS)
    link.reset_input_buffer()
    return link


class Link:
    """Serial connection that survives the board being unplugged."""

    def __init__(self, explicit: str | None, echo: bool) -> None:
        self.explicit = explicit
        self.echo = echo
        self.port: serial.Serial | None = None
        self.last_attempt = 0.0

    def ensure(self) -> None:
        if self.port is not None and self.port.is_open:
            return
        if time.monotonic() - self.last_attempt < 2.0:
            return
        self.last_attempt = time.monotonic()
        self.port = open_port(self.explicit)

    def send(self, line: str) -> None:
        self.ensure()
        if self.port is None:
            return
        try:
            self.port.write(f"{line}\n".encode())
            print(f"-> {line}")
        except serial.SerialException as error:
            print(f"[serial] write failed, will reopen: {error}")
            self.close()

    def drain(self) -> None:
        """Print whatever the board sent back."""
        if self.port is None or not self.echo:
            return
        try:
            data = self.port.read(4096)
        except serial.SerialException:
            self.close()
            return
        if data:
            for line in data.decode(errors="replace").splitlines():
                if line.strip():
                    print(f"<- {line.strip()}")

    def close(self) -> None:
        if self.port is not None:
            try:
                self.port.close()
            except Exception:
                pass
        self.port = None


async def pump_serial(link: Link) -> None:
    """Drain the board's output and keep the link alive."""
    last_ping = 0.0
    while True:
        link.ensure()
        link.drain()
        if time.monotonic() - last_ping >= PING_SECONDS:
            link.send("PING")
            last_ping = time.monotonic()
        await asyncio.sleep(0.05)


async def pump_ring(link: Link) -> None:
    """Subscribe to the bridge and translate its events into serial lines."""
    last_gesture: tuple[str, float] = ("", 0.0)
    last_hr = 0
    last_steps = -1

    while True:
        try:
            async with websockets.connect(WS_URL) as ws:
                print(f"[ws] connected to {WS_URL}")
                # Gestures only fire in gesture mode, so ask for it.
                await ws.send(json.dumps({"mode": "gesture"}))

                async for message in ws:
                    event = json.loads(message)
                    kind = event.get("type")

                    if kind == "gesture" and event.get("name"):
                        # The bridge replays the latest of each event type to a
                        # newly connected client. That is right for state like
                        # heart rate, but a stale gesture must not re-fire an
                        # action, so ignore anything that is not fresh.
                        if time.time() - event.get("t", 0) > STALE_SECONDS:
                            continue
                        name = event["name"]
                        previous, when = last_gesture
                        if name == previous and time.monotonic() - when < GESTURE_COOLDOWN:
                            continue
                        last_gesture = (name, time.monotonic())
                        link.send(f"G:{name}")

                    elif kind == "hr" and event.get("bpm") and event["bpm"] != last_hr:
                        last_hr = event["bpm"]
                        link.send(f"HR:{last_hr}")

                    elif kind == "activity" and event.get("steps") != last_steps:
                        last_steps = event["steps"]
                        link.send(f"STEPS:{last_steps}")

        except (OSError, websockets.WebSocketException) as error:
            print(f"[ws] {error}; retrying in 2s — is bridge.py running?")
            await asyncio.sleep(2)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="serial device; auto-detected when omitted")
    parser.add_argument("--list", action="store_true", help="list serial ports and exit")
    parser.add_argument("--echo", action="store_true", help="print lines coming back")
    args = parser.parse_args()

    if args.list:
        list_ports()
        return

    link = Link(args.port, args.echo)
    link.ensure()
    if link.port is None:
        print("\nNo Arduino-looking serial port found. Plug the board in, then:")
        print("  python serial_link.py --list")
        print("Continuing anyway — it will connect as soon as the board appears.\n")

    await asyncio.gather(pump_ring(link), pump_serial(link))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye")
        sys.exit(0)
