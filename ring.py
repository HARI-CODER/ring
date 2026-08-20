"""PBL Halo 2 client.

The ring speaks the Colmi R02 protocol over Nordic UART: fixed 16-byte frames,
byte 0 = command, bytes 1..14 = payload, byte 15 = sum(bytes[0:15]) & 0xFF.

macOS keeps the ring connected at the OS level, which stops it advertising, so
we attach via retrievePeripheralsWithIdentifiers: instead of scanning.

Usage:
    python ring.py battery
    python ring.py hr        # live heart rate
    python ring.py spo2      # live blood oxygen
    python ring.py raw       # just dump every frame
"""

import sys

import objc
from CoreBluetooth import CBCentralManager, CBUUID
from Foundation import NSUUID, NSObject
from PyObjCTools import AppHelper

RING_UUID = "3B6D1936-96C3-1BDF-DFDE-7866801EF55D"

UART_RX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # host -> ring
UART_TX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # ring -> host

CMD_BATTERY = 0x03
CMD_REALTIME_START = 0x69
CMD_REALTIME_CONTINUE = 0x1E
CMD_REALTIME_STOP = 0x6A

READING_HEART_RATE = 1
READING_SPO2 = 2


def frame(command: int, payload: bytes = b"") -> bytes:
    """Build a 16-byte Colmi frame with its trailing checksum."""
    packet = bytearray(16)
    packet[0] = command
    packet[1 : 1 + len(payload)] = payload
    packet[15] = sum(packet[:15]) & 0xFF
    return bytes(packet)


def checksum_ok(raw: bytes) -> bool:
    return len(raw) == 16 and raw[15] == sum(raw[:15]) & 0xFF


def decode_frame(raw: bytes) -> bool:
    """Print one frame. Returns True when the exchange is finished."""
    mark = "" if checksum_ok(raw) else "  <bad checksum>"
    hexed = " ".join(f"{b:02x}" for b in raw)
    command = raw[0]

    if command == CMD_BATTERY:
        state = {0: "not charging", 1: "charging", 2: "full"}.get(raw[2], f"0x{raw[2]:02x}")
        print(f"Battery: {raw[1]}%  ({state}){mark}")
        return True

    if command == CMD_REALTIME_START:
        kind, err, value = raw[1], raw[2], raw[3]
        if err:
            print(f"ring reports error 0x{err:02x} (keep it on, snug, still){mark}")
        elif value:
            label = "heart rate" if kind == READING_HEART_RATE else "SpO2"
            unit = "bpm" if kind == READING_HEART_RATE else "%"
            print(f"{label}: {value} {unit}{mark}")
        return False

    # Ack for the keepalive (0x1E | 0x80). Pure noise during a live stream.
    if command == (CMD_REALTIME_CONTINUE | 0x80):
        return False

    print(f"[frame] cmd=0x{command:02x}  {hexed}{mark}")
    return False


class Delegate(NSObject):
    def initWithMode_(self, mode):
        self = objc.super(Delegate, self).init()
        self.mode = mode
        self.peripheral = None
        self.rx = None
        self.opened = False
        self.ticks = 0
        return self

    # --- connection --------------------------------------------------------

    def centralManagerDidUpdateState_(self, central):
        if central.state() != 5:
            print(f"Bluetooth not powered on (state={central.state()}).")
            return AppHelper.stopEventLoop()
        ident = NSUUID.alloc().initWithUUIDString_(RING_UUID)
        found = list(central.retrievePeripheralsWithIdentifiers_([ident]))
        if not found:
            print("Ring not retrievable. Re-run scan.py to get a fresh UUID.")
            return AppHelper.stopEventLoop()
        self.peripheral = found[0]
        central.connectPeripheral_options_(self.peripheral, None)

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        peripheral.setDelegate_(self)
        peripheral.discoverServices_(None)

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
        print(f"Disconnected: {error}")
        AppHelper.stopEventLoop()

    # --- discovery ---------------------------------------------------------

    def peripheral_didDiscoverServices_(self, peripheral, error):
        for service in peripheral.services() or []:
            peripheral.discoverCharacteristics_forService_(None, service)

    def peripheral_didDiscoverCharacteristicsForService_error_(self, p, service, error):
        for char in service.characteristics() or []:
            uuid = str(char.UUID()).upper()
            if uuid == UART_TX:
                p.setNotifyValue_forCharacteristic_(True, char)
            elif uuid == UART_RX:
                self.rx = char
        # Fires once per service; only open the exchange on the first one that
        # actually gave us the UART write characteristic.
        if self.rx is not None and not self.opened:
            self.opened = True
            self.performSelector_withObject_afterDelay_("sendOpening:", None, 0.6)

    # --- sending -----------------------------------------------------------

    def send_(self, data: bytes):
        from Foundation import NSData

        payload = NSData.dataWithBytes_length_(data, len(data))
        # 1 == CBCharacteristicWriteWithoutResponse
        self.peripheral.writeValue_forCharacteristic_type_(payload, self.rx, 1)

    def sendOpening_(self, _):
        if self.mode == "battery":
            print("Requesting battery...")
            self.send_(frame(CMD_BATTERY))
        elif self.mode in ("hr", "spo2"):
            kind = READING_HEART_RATE if self.mode == "hr" else READING_SPO2
            print(f"Starting live {self.mode}. Wear the ring snugly. Ctrl-C to stop.\n")
            self.send_(frame(CMD_REALTIME_START, bytes([kind, 1])))
            self.performSelector_withObject_afterDelay_("keepAlive:", None, 3.0)
        else:
            print("Listening for unsolicited frames. Ctrl-C to stop.\n")

    def keepAlive_(self, _):
        """The ring stops streaming unless nudged every few seconds."""
        self.send_(frame(CMD_REALTIME_CONTINUE))
        self.ticks += 1
        self.performSelector_withObject_afterDelay_("keepAlive:", None, 3.0)

    # --- receiving ---------------------------------------------------------

    def peripheral_didUpdateValueForCharacteristic_error_(self, p, char, error):
        if error or char.value() is None:
            return
        raw = bytes(char.value())
        if str(char.UUID()).upper() != UART_TX:
            return
        if decode_frame(raw):
            AppHelper.stopEventLoop()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "raw"
    delegate = Delegate.alloc().initWithMode_(mode)
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
