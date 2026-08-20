"""Hunt for a faster accelerometer sample rate.

Gesture recognition needs tens of samples per second; the default 0xA1 stream
delivers about one. This tries a series of candidate start payloads and reports
the achieved accel sample rate for each, so we can see whether any parameter
raises it.

Only the 0xA1 command family and its payload bytes are probed. The second
custom service (DE5BF728) is deliberately left alone -- an unknown write
characteristic on a wearable is very often a DFU/bootloader entry point.

    python rate.py
"""

import time

import objc
from CoreBluetooth import CBCentralManager
from Foundation import NSData, NSUUID, NSObject
from PyObjCTools import AppHelper

from ring import RING_UUID, UART_RX, UART_TX, frame

CMD_RAW_SENSOR = 0xA1
SECONDS_PER_TRIAL = 8.0

# (label, payload after the command byte)
TRIALS = [
    ("baseline [3,1]", bytes([3, 1])),
    ("[3,1,1]", bytes([3, 1, 1])),
    ("[3,1,10]", bytes([3, 1, 10])),
    ("[3,1,25]", bytes([3, 1, 25])),
    ("[3,1,50]", bytes([3, 1, 50])),
    ("[3,1,100]", bytes([3, 1, 100])),
    ("[3,1,0,50]", bytes([3, 1, 0, 50])),
    ("[3,50,1]", bytes([3, 50, 1])),
    ("subtype 7", bytes([7, 1])),
    ("subtype 8", bytes([8, 1])),
    ("subtype 9", bytes([9, 1])),
    ("subtype 10", bytes([10, 1])),
]


class Rate(NSObject):
    def init(self):
        self = objc.super(Rate, self).init()
        self.rx = None
        self.opened = False
        self.peripheral = None
        self.index = -1
        self.count = 0
        self.started = 0.0
        self.results = []
        return self

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
            self.nextTrial_(None)

    def send_(self, payload: bytes):
        data = NSData.dataWithBytes_length_(payload, len(payload))
        self.peripheral.writeValue_forCharacteristic_type_(data, self.rx, 1)

    def nextTrial_(self, _):
        if self.index >= 0:
            label, payload = TRIALS[self.index]
            elapsed = time.monotonic() - self.started
            hz = self.count / elapsed if elapsed else 0
            self.results.append((label, hz, self.count))
            print(f"  {label:<16} {self.count:3d} samples in {elapsed:.1f}s  ->  {hz:.2f} Hz")
            self.send_(frame(CMD_RAW_SENSOR, bytes([payload[0], 0])))

        self.index += 1
        if self.index >= len(TRIALS):
            print("\n--- best first ---")
            for label, hz, count in sorted(self.results, key=lambda r: -r[1]):
                print(f"  {hz:6.2f} Hz  {label}")
            return AppHelper.stopEventLoop()

        label, payload = TRIALS[self.index]
        print(f"\n>>> {label}")
        self.count = 0
        self.started = time.monotonic()
        self.send_(frame(CMD_RAW_SENSOR, payload))
        self.performSelector_withObject_afterDelay_("nextTrial:", None, SECONDS_PER_TRIAL)

    def peripheral_didUpdateValueForCharacteristic_error_(self, p, char, error):
        if error or char.value() is None:
            return
        if str(char.UUID()).upper() != UART_TX:
            return
        raw = bytes(char.value())
        if len(raw) >= 2 and raw[0] == CMD_RAW_SENSOR and raw[1] == 0x03:
            self.count += 1


def main() -> None:
    delegate = Rate.alloc().init()
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
