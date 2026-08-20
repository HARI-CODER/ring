"""BLE -> WebSocket bridge for the PBL Halo 2.

The browser cannot reach this ring: Web Bluetooth needs a scan to pick a device,
and the ring stops advertising while macOS holds it connected. So CoreBluetooth
stays here in Python, and the UI subscribes over a WebSocket.

CoreBluetooth requires its run loop on the main thread, so the asyncio
WebSocket server runs on a worker thread and receives samples via
call_soon_threadsafe.

    python bridge.py            # ws://127.0.0.1:8765

Every message is JSON: {"type": ..., "t": <unix seconds>, ...}
    battery  {"percent": 90, "charging": false}
    hr       {"bpm": 92}
    spo2     {"percent": 97}
    accel    {"x": .., "y": .., "z": .., "g": 1.01}   raw counts + magnitude
    ppg      {"channel": "a"|"b", "value": 6900, "saturated": false}
    activity {"steps": 87, "distance_cm": 2088, "calories": 48}
"""

import asyncio
import json
import threading
import time
from collections import deque

import objc
import websockets
from CoreBluetooth import CBCentralManager
from Foundation import NSData, NSUUID, NSObject
from PyObjCTools import AppHelper

from gestures import Segmenter, Store
from ring import (
    CMD_BATTERY,
    CMD_REALTIME_CONTINUE,
    CMD_REALTIME_START,
    CMD_REALTIME_STOP,
    READING_HEART_RATE,
    RING_UUID,
    UART_RX,
    UART_TX,
    frame,
)

HOST, PORT = "127.0.0.1", 8765

CMD_RAW_SENSOR = 0xA1
CMD_ACTIVITY = 0x73
SUB_ACCEL = 3
ACTIVITY_SUB = 0x12

COUNTS_PER_G = 8192.0
PUMP_SECONDS = 3.0
# In gesture mode the start command is used as a poll: each one returns a
# sample, which lifts the effective rate from ~1 Hz to ~10 Hz.
GESTURE_POLL_SECONDS = 0.1
MODE_WINDOW_SECONDS = 45.0  # heart rate needs ~25s to lock on, so windows are long

# The ring exposes one sensor mode at a time: "hr", "motion" or "gesture".
current_mode: str | None = None
pinned_mode: str | None = None  # set by a client to stop alternating

store = Store().load()
segmenter = Segmenter()
recording_as: str | None = None  # name to save the next captured gesture under

# Rolling window of recent samples, used to report how much of the polled data
# is actually fresh rather than the same value repeated.
recent_samples: deque = deque(maxlen=40)

# --- fan-out ---------------------------------------------------------------

clients: set = set()
loop: asyncio.AbstractEventLoop | None = None
latest: dict = {}


def publish(kind: str, **fields) -> None:
    """Called from the CoreBluetooth thread; hands off to the asyncio loop."""
    message = {"type": kind, "t": time.time(), **fields}
    latest[kind] = message
    if loop is None:
        return
    payload = json.dumps(message)
    loop.call_soon_threadsafe(_fanout, payload)


def _fanout(payload: str) -> None:
    for ws in list(clients):
        asyncio.create_task(_safe_send(ws, payload))


async def _safe_send(ws, payload: str) -> None:
    try:
        await ws.send(payload)
    except Exception:
        clients.discard(ws)


async def handler(ws) -> None:
    clients.add(ws)
    print(f"[ws] client connected ({len(clients)} total)")
    try:
        # Replay the most recent value of each stream so a fresh page is not blank.
        for message in latest.values():
            await ws.send(json.dumps(message))
        await ws.send(json.dumps({"type": "gestures", "t": time.time(), "items": store.summary()}))

        async for message in ws:
            global pinned_mode, recording_as
            try:
                command = json.loads(message)
            except ValueError:
                continue

            # Pin a sensor: {"mode": "hr" | "motion" | "gesture" | "auto"}
            wanted = command.get("mode")
            if wanted in ("hr", "motion", "gesture"):
                pinned_mode = wanted
            elif wanted == "auto":
                pinned_mode = None

            # Arm recording: the next captured gesture is saved under this name.
            if "record" in command:
                name = str(command["record"]).strip()
                recording_as = name or None
                pinned_mode = "gesture"
                segmenter.reset()
                publish("gesture_state", capturing=False, arming=recording_as)

            if command.get("cancel"):
                recording_as = None
                segmenter.reset()
                publish("gesture_state", capturing=False, arming=None)

            if "delete" in command:
                store.delete(str(command["delete"]))
                publish("gestures", items=store.summary())
    finally:
        clients.discard(ws)
        print(f"[ws] client gone ({len(clients)} total)")


def serve() -> None:
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        async with websockets.serve(handler, HOST, PORT):
            print(f"[ws] listening on ws://{HOST}:{PORT}")
            await asyncio.Future()

    loop.run_until_complete(run())


# --- BLE -------------------------------------------------------------------


class Bridge(NSObject):
    def init(self):
        self = objc.super(Bridge, self).init()
        self.rx = None
        self.opened = False
        self.peripheral = None
        return self

    def centralManagerDidUpdateState_(self, central):
        if central.state() != 5:
            print(f"Bluetooth not powered on (state={central.state()}).")
            AppHelper.stopEventLoop()
            return
        ident = NSUUID.alloc().initWithUUIDString_(RING_UUID)
        found = list(central.retrievePeripheralsWithIdentifiers_([ident]))
        if not found:
            print("Ring not retrievable; re-run scan.py for a fresh UUID.")
            AppHelper.stopEventLoop()
            return
        self.peripheral = found[0]
        central.connectPeripheral_options_(self.peripheral, None)

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        print("[ble] connected")
        peripheral.setDelegate_(self)
        peripheral.discoverServices_(None)

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
        print(f"[ble] disconnected: {error}")
        AppHelper.stopEventLoop()

    def peripheral_didDiscoverServices_(self, peripheral, error):
        for service in peripheral.services() or []:
            peripheral.discoverCharacteristics_forService_(None, service)

    def peripheral_didDiscoverCharacteristicsForService_error_(self, p, service, error):
        for char in service.characteristics() or []:
            if char.properties() & 0x10:
                p.setNotifyValue_forCharacteristic_(True, char)
            if str(char.UUID()).upper() == UART_RX:
                self.rx = char
        if self.rx is not None and not self.opened:
            self.opened = True
            self.send_(frame(CMD_BATTERY))
            self.pump_(None)

    def send_(self, payload: bytes):
        data = NSData.dataWithBytes_length_(payload, len(payload))
        self.peripheral.writeValue_forCharacteristic_type_(data, self.rx, 1)

    def pump_(self, _):
        """Re-arm the active stream; it lapses after a few seconds otherwise.

        The ring runs ONE sensor mode at a time -- with the raw stream active,
        heart-rate replies never arrive. So we time-slice, unless a client has
        pinned a mode.
        """
        global current_mode

        wanted = pinned_mode
        if wanted is None:  # auto: alternate windows
            window = int(time.monotonic() / MODE_WINDOW_SECONDS) % 2
            wanted = "hr" if window == 0 else "motion"

        if wanted != current_mode:
            # Stop the outgoing stream before starting the new one.
            if current_mode == "hr":
                self.send_(frame(CMD_REALTIME_STOP, bytes([READING_HEART_RATE, 0, 0])))
            elif current_mode in ("motion", "gesture"):
                self.send_(frame(CMD_RAW_SENSOR, bytes([SUB_ACCEL, 0])))
                segmenter.reset()
            current_mode = wanted
            publish("mode", mode=wanted, pinned=pinned_mode is not None)
            # Start ONCE on entry. Re-issuing start restarts heart-rate
            # acquisition, which needs ~10s uninterrupted to produce a reading.
            if wanted == "hr":
                self.send_(frame(CMD_REALTIME_START, bytes([READING_HEART_RATE, 1])))
            else:
                self.send_(frame(CMD_RAW_SENSOR, bytes([SUB_ACCEL, 1])))

        elif current_mode == "hr":
            self.send_(frame(CMD_REALTIME_CONTINUE))
        else:
            # The raw stream lapses; re-arming doubles as the gesture-mode poll.
            self.send_(frame(CMD_RAW_SENSOR, bytes([SUB_ACCEL, 1])))

        delay = GESTURE_POLL_SECONDS if current_mode == "gesture" else PUMP_SECONDS
        self.performSelector_withObject_afterDelay_("pump:", None, delay)

    def peripheral_didUpdateValueForCharacteristic_error_(self, p, char, error):
        if error or char.value() is None:
            return
        if str(char.UUID()).upper() != UART_TX:
            return
        raw = bytes(char.value())
        if len(raw) < 16:
            return
        dispatch(raw)


def feed_gesture(x: int, y: int, z: int) -> None:
    """Run one polled sample through the segmenter, then record or recognise."""
    global recording_as

    now = time.time()
    recent_samples.append((now, x, y, z))

    # How much of the polled stream is genuinely new. If this sits near zero
    # while you are moving, the ring is repeating a cached value and gestures
    # cannot work -- surfaced in the UI rather than failing silently.
    if len(recent_samples) > 4:
        span = recent_samples[-1][0] - recent_samples[0][0]
        distinct = len({s[1:] for s in recent_samples})
        publish(
            "gesture_signal",
            sample_hz=round(len(recent_samples) / span, 1) if span > 0 else 0,
            fresh_hz=round(distinct / span, 1) if span > 0 else 0,
        )

    points = segmenter.feed(
        now, x / COUNTS_PER_G, y / COUNTS_PER_G, z / COUNTS_PER_G
    )
    publish("gesture_state", capturing=segmenter.active, arming=recording_as)

    if points is None:
        return

    if recording_as is not None:
        name = recording_as
        recording_as = None
        result = store.add(name, points)
        publish("gesture_saved", name=name, samples=len(points), **result)
        publish("gestures", items=store.summary())
    else:
        result = store.match(points)
        publish("gesture", samples=len(points), **result)


def dispatch(raw: bytes) -> None:
    command = raw[0]

    if command == CMD_BATTERY:
        publish("battery", percent=raw[1], charging=raw[2] == 1)

    elif command == CMD_REALTIME_START:
        kind, err, value = raw[1], raw[2], raw[3]
        if err or not value:
            return
        if kind == READING_HEART_RATE:
            publish("hr", bpm=value)
        else:
            publish("spo2", percent=value)

    elif command == CMD_RAW_SENSOR:
        stream = raw[1]
        if stream == 0x03:
            x = int.from_bytes(raw[2:4], "big", signed=True)
            y = int.from_bytes(raw[4:6], "big", signed=True)
            z = int.from_bytes(raw[6:8], "big", signed=True)
            g = (x * x + y * y + z * z) ** 0.5 / COUNTS_PER_G
            publish("accel", x=x, y=y, z=z, g=round(g, 3))
            if current_mode == "gesture":
                feed_gesture(x, y, z)
        elif stream in (0x01, 0x02):
            value = int.from_bytes(raw[2:4], "big")
            publish(
                "ppg",
                channel="a" if stream == 0x01 else "b",
                value=value,
                saturated=value == 0x7FFF,
            )

    elif command == CMD_ACTIVITY and raw[1] == ACTIVITY_SUB:
        publish(
            "activity",
            steps=int.from_bytes(raw[2:5], "big"),
            distance_cm=int.from_bytes(raw[5:8], "big"),
            calories=int.from_bytes(raw[8:11], "big"),
        )


def main() -> None:
    threading.Thread(target=serve, daemon=True).start()
    delegate = Bridge.alloc().init()
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
