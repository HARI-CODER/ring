"""Probe the ring for undocumented sensor streams (IMU / accelerometer / PPG).

Sends a scripted sequence of candidate command frames while listening on EVERY
notify characteristic at once, so a response arriving on the second custom
service (DE5BF729) or on FEA1 is not missed.

Deliberately targeted, not a brute-force opcode sweep: unknown opcodes in this
family include factory-reset / unbind / DFU, which would wipe the ring.

Usage:
    python explore.py raw        # sweep raw-sensor subtypes on cmd 0xA1
    python explore.py channels   # sit idle, just show which channels talk
"""

import sys
import time

import objc
from CoreBluetooth import CBCentralManager
from Foundation import NSData, NSUUID, NSObject
from PyObjCTools import AppHelper

from ring import RING_UUID, UART_RX, UART_TX, checksum_ok, frame

CMD_RAW_SENSOR = 0xA1
CMD_REALTIME_CONTINUE = 0x1E

# Friendly names for every notify channel the ring exposes.
CHANNELS = {
    UART_TX: "uart",
    "DE5BF729-D711-4E47-AF26-65E3012A5DC7": "de5b",
    "0000FEA1-0000-1000-8000-00805F9B34FB": "fea1",
}


def build_probes(mode: str):
    """Return a list of (label, frame-or-None) steps. None = just listen."""
    if mode == "channels":
        return [("idle listen", None)] * 12

    probes = []
    for subtype in range(1, 7):
        probes.append((f"0xA1 subtype={subtype} start", frame(CMD_RAW_SENSOR, bytes([subtype, 1]))))
        probes.append((f"0xA1 subtype={subtype} listen", None))
        probes.append((f"0xA1 subtype={subtype} listen", None))
        probes.append((f"0xA1 subtype={subtype} stop", frame(CMD_RAW_SENSOR, bytes([subtype, 0]))))
    return probes


class Prober(NSObject):
    def initWithMode_(self, mode):
        self = objc.super(Prober, self).init()
        self.probes = build_probes(mode)
        self.step = 0
        self.rx = None
        self.opened = False
        self.peripheral = None
        self.label = "(before any probe)"
        self.seen = {}
        self.start = time.monotonic()
        return self

    # --- connection --------------------------------------------------------

    def centralManagerDidUpdateState_(self, central):
        if central.state() != 5:
            print(f"Bluetooth not powered on (state={central.state()}).")
            return AppHelper.stopEventLoop()
        ident = NSUUID.alloc().initWithUUIDString_(RING_UUID)
        found = list(central.retrievePeripheralsWithIdentifiers_([ident]))
        if not found:
            print("Ring not retrievable; re-run scan.py for a fresh UUID.")
            return AppHelper.stopEventLoop()
        self.peripheral = found[0]
        central.connectPeripheral_options_(self.peripheral, None)

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        peripheral.setDelegate_(self)
        peripheral.discoverServices_(None)

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
        print(f"Disconnected: {error}")
        AppHelper.stopEventLoop()

    def peripheral_didDiscoverServices_(self, peripheral, error):
        for service in peripheral.services() or []:
            peripheral.discoverCharacteristics_forService_(None, service)

    def peripheral_didDiscoverCharacteristicsForService_error_(self, p, service, error):
        for char in service.characteristics() or []:
            uuid = str(char.UUID()).upper()
            if char.properties() & 0x10:  # notify
                p.setNotifyValue_forCharacteristic_(True, char)
            if uuid == UART_RX:
                self.rx = char
        if self.rx is not None and not self.opened:
            self.opened = True
            self.performSelector_withObject_afterDelay_("nextProbe:", None, 1.0)

    # --- probe driver ------------------------------------------------------

    def nextProbe_(self, _):
        if self.step >= len(self.probes):
            print("\n--- summary: frames seen per channel/command ---")
            for key, count in sorted(self.seen.items()):
                print(f"  {key}: {count}")
            return AppHelper.stopEventLoop()

        label, payload = self.probes[self.step]
        self.step += 1
        self.label = label
        if payload is not None:
            print(f"\n>>> {label}")
            data = NSData.dataWithBytes_length_(payload, len(payload))
            self.peripheral.writeValue_forCharacteristic_type_(data, self.rx, 1)
        self.performSelector_withObject_afterDelay_("nextProbe:", None, 2.0)

    # --- receiving ---------------------------------------------------------

    def peripheral_didUpdateValueForCharacteristic_error_(self, p, char, error):
        if error or char.value() is None:
            return
        raw = bytes(char.value())
        uuid = str(char.UUID()).upper()
        channel = CHANNELS.get(uuid, uuid[:8])

        command = raw[0] if raw else -1
        if command == (CMD_REALTIME_CONTINUE | 0x80):
            return  # keepalive ack

        key = f"{channel} cmd=0x{command:02x}"
        self.seen[key] = self.seen.get(key, 0) + 1

        mark = "" if checksum_ok(raw) else " <bad cksum>"
        hexed = " ".join(f"{b:02x}" for b in raw)
        elapsed = time.monotonic() - self.start
        print(f"[{elapsed:6.1f}s] {channel:5s} {len(raw):3d}B  {hexed}{mark}")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "raw"
    delegate = Prober.alloc().initWithMode_(mode)
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
