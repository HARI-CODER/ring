"""Live accelerometer / raw-sensor stream from the PBL Halo 2.

Discovered empirically (see explore.py). Command 0xA1 with payload
[subtype, 1] starts a raw stream; [subtype, 0] stops it. The ring then emits a
repeating triplet of 16-byte frames:

    a1 01 <u16 be> ...   PPG channel A (raw optical counts)
    a1 02 <u16 be> ...   PPG channel B (0x7FFF = saturated / no skin contact)
    a1 03 <i16 i16 i16>  accelerometer X, Y, Z  (big-endian, signed)

Accel scale is inferred, not documented: at rest the vector magnitude sits near
8192, so SCALE=8192 counts/g (i.e. a +/-4g range on a 16-bit sensor). Hold the
ring still on a table and check that |a| reads ~1.00 g to confirm on your unit.

Usage:
    python imu.py            # decoded accel, ~1 Hz
    python imu.py --raw      # also show the PPG channels and unknown frames
"""

import struct
import sys
import time

import objc
from CoreBluetooth import CBCentralManager
from Foundation import NSData, NSUUID, NSObject
from PyObjCTools import AppHelper

from ring import RING_UUID, UART_RX, UART_TX, checksum_ok, frame

CMD_RAW_SENSOR = 0xA1
SUB_ACCEL = 3  # any subtype starts the stream; 3 carries the fullest payload

STREAM_ACCEL = 0x03
STREAM_PPG_A = 0x01
STREAM_PPG_B = 0x02

COUNTS_PER_G = 8192.0
RESTART_SECONDS = 3.0  # ring stops streaming unless nudged


def decode_accel(raw: bytes):
    """bytes 2..8 of an 'a1 03' frame are X, Y, Z as big-endian int16."""
    return struct.unpack(">hhh", raw[2:8])


class Imu(NSObject):
    def initWithRaw_(self, show_raw):
        self = objc.super(Imu, self).init()
        self.show_raw = show_raw
        self.rx = None
        self.opened = False
        self.peripheral = None
        self.start_time = time.monotonic()
        self.samples = 0
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
            if char.properties() & 0x10:
                p.setNotifyValue_forCharacteristic_(True, char)
            if uuid == UART_RX:
                self.rx = char
        if self.rx is not None and not self.opened:
            self.opened = True
            print("Streaming accelerometer. Move your hand. Ctrl-C to stop.\n")
            print(f"{'time':>8}  {'X':>7} {'Y':>7} {'Z':>7}   {'|a| (g)':>8}")
            self.pump_(None)

    # --- driving the stream ------------------------------------------------

    def send_(self, payload: bytes):
        data = NSData.dataWithBytes_length_(payload, len(payload))
        self.peripheral.writeValue_forCharacteristic_type_(data, self.rx, 1)

    def pump_(self, _):
        """Re-issue the start command; the stream lapses without it."""
        self.send_(frame(CMD_RAW_SENSOR, bytes([SUB_ACCEL, 1])))
        self.performSelector_withObject_afterDelay_("pump:", None, RESTART_SECONDS)

    # --- receiving ---------------------------------------------------------

    def peripheral_didUpdateValueForCharacteristic_error_(self, p, char, error):
        if error or char.value() is None:
            return
        if str(char.UUID()).upper() != UART_TX:
            return
        raw = bytes(char.value())
        if len(raw) < 16 or raw[0] != CMD_RAW_SENSOR:
            if self.show_raw and len(raw) >= 2:
                print(f"  [other] {' '.join(f'{b:02x}' for b in raw)}")
            return

        stream = raw[1]
        elapsed = time.monotonic() - self.start_time

        if stream == STREAM_ACCEL:
            x, y, z = decode_accel(raw)
            magnitude = (x * x + y * y + z * z) ** 0.5 / COUNTS_PER_G
            flag = "" if checksum_ok(raw) else "  <bad cksum>"
            print(f"{elapsed:8.1f}  {x:7d} {y:7d} {z:7d}   {magnitude:8.2f}{flag}")
            self.samples += 1
        elif self.show_raw and stream in (STREAM_PPG_A, STREAM_PPG_B):
            value = struct.unpack(">H", raw[2:4])[0]
            name = "ppg-a" if stream == STREAM_PPG_A else "ppg-b"
            note = "  (saturated)" if value == 0x7FFF else ""
            print(f"{elapsed:8.1f}  {name}: {value}{note}")


def main() -> None:
    show_raw = "--raw" in sys.argv
    delegate = Imu.alloc().initWithRaw_(show_raw)
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
