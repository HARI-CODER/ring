"""Test whether polling beats subscribing for accelerometer sample rate.

The ring pushes the raw stream at only ~1 Hz. But every 0xA1 start command
appears to trigger an immediate sample, so issuing that command rapidly may act
as a poll and lift the effective rate into gesture-usable territory.

    python poll.py [interval_ms]      default 50ms
"""

import sys
import time

import objc
from CoreBluetooth import CBCentralManager
from Foundation import NSData, NSUUID, NSObject
from PyObjCTools import AppHelper

from ring import RING_UUID, UART_RX, UART_TX, frame

CMD_RAW_SENSOR = 0xA1
SUB_ACCEL = 3
TEST_SECONDS = 12.0


class Poller(NSObject):
    def initWithInterval_(self, interval):
        self = objc.super(Poller, self).init()
        self.interval = interval
        self.rx = None
        self.opened = False
        self.peripheral = None
        self.samples = []
        self.polls = 0
        self.started = 0.0
        return self

    def centralManagerDidUpdateState_(self, central):
        if central.state() != 5:
            return AppHelper.stopEventLoop()
        ident = NSUUID.alloc().initWithUUIDString_(RING_UUID)
        found = list(central.retrievePeripheralsWithIdentifiers_([ident]))
        if not found:
            print("Ring not retrievable.")
            return AppHelper.stopEventLoop()
        self.peripheral = found[0]
        central.connectPeripheral_options_(self.peripheral, None)

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        peripheral.setDelegate_(self)
        peripheral.discoverServices_(None)

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
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
            print(f"Polling every {self.interval * 1000:.0f}ms for {TEST_SECONDS:.0f}s...")
            self.started = time.monotonic()
            self.poll_(None)

    def send_(self, payload: bytes):
        data = NSData.dataWithBytes_length_(payload, len(payload))
        self.peripheral.writeValue_forCharacteristic_type_(data, self.rx, 1)

    def poll_(self, _):
        elapsed = time.monotonic() - self.started
        if elapsed >= TEST_SECONDS:
            unique = len({(s[1], s[2], s[3]) for s in self.samples})
            print(f"\npolls sent      : {self.polls}")
            print(f"accel replies   : {len(self.samples)}  ->  {len(self.samples)/elapsed:.1f} Hz")
            print(f"distinct values : {unique}  ->  {unique/elapsed:.1f} Hz of real motion data")
            if self.samples:
                gaps = [
                    self.samples[i][0] - self.samples[i - 1][0]
                    for i in range(1, len(self.samples))
                ]
                if gaps:
                    print(f"median gap      : {sorted(gaps)[len(gaps)//2]*1000:.0f} ms")
            return AppHelper.stopEventLoop()

        self.send_(frame(CMD_RAW_SENSOR, bytes([SUB_ACCEL, 1])))
        self.polls += 1
        self.performSelector_withObject_afterDelay_("poll:", None, self.interval)

    def peripheral_didUpdateValueForCharacteristic_error_(self, p, char, error):
        if error or char.value() is None:
            return
        if str(char.UUID()).upper() != UART_TX:
            return
        raw = bytes(char.value())
        if len(raw) >= 8 and raw[0] == CMD_RAW_SENSOR and raw[1] == 0x03:
            x = int.from_bytes(raw[2:4], "big", signed=True)
            y = int.from_bytes(raw[4:6], "big", signed=True)
            z = int.from_bytes(raw[6:8], "big", signed=True)
            self.samples.append((time.monotonic(), x, y, z))


def main() -> None:
    interval = (float(sys.argv[1]) if len(sys.argv) > 1 else 50.0) / 1000.0
    delegate = Poller.alloc().initWithInterval_(interval)
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
