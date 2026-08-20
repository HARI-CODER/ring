"""Talk to the ring even while macOS already holds it connected.

A BLE peripheral stops advertising once something connects to it, so a normal
scan (scan.py / bleak) can never find it. But CoreBluetooth lets any app on the
machine attach to an already-connected peripheral via
retrievePeripheralsWithIdentifiers: -- no scan, no unpairing needed.

Usage:
    python connect_paired.py                       # use RING_UUID below
    python connect_paired.py <peripheral-uuid>
"""

import sys

import objc
from CoreBluetooth import (
    CBCentralManager,
    CBUUID,
    CBCharacteristicPropertyIndicate,
    CBCharacteristicPropertyNotify,
)
from Foundation import NSUUID, NSObject
from PyObjCTools import AppHelper

# From scan.py output. This is a macOS-local identifier, not the ring's MAC.
RING_UUID = "46818C74-EA01-23B5-A3ED-D0F39223941A"

VENDOR_SERVICE = "FEE7"  # what the ring advertises
KNOWN_SERVICES = [VENDOR_SERVICE, "180F", "180A", "180D", "1812"]

LABELS = {
    "2A19": "Battery Level",
    "2A29": "Manufacturer",
    "2A24": "Model Number",
    "2A26": "Firmware Rev",
    "2A27": "Hardware Rev",
    "2A28": "Software Rev",
}

NOTIFY_MASK = CBCharacteristicPropertyNotify | CBCharacteristicPropertyIndicate


def hexdump(data) -> str:
    raw = bytes(data)
    return " ".join(f"{b:02x}" for b in raw)


class Delegate(NSObject):
    def initWithTarget_(self, target):
        self = objc.super(Delegate, self).init()
        self.target = target
        self.peripheral = None
        self.pending = 0
        return self

    # --- central manager ---------------------------------------------------

    def centralManagerDidUpdateState_(self, central):
        if central.state() != 5:  # CBManagerStatePoweredOn
            print(f"Bluetooth not ready (state={central.state()}). Is BT on?")
            return

        ident = NSUUID.alloc().initWithUUIDString_(self.target)
        found = list(central.retrievePeripheralsWithIdentifiers_([ident])) if ident else []

        if not found:
            print("Identifier lookup returned nothing; trying connected-by-service...")
            found = list(
                central.retrieveConnectedPeripheralsWithServices_(
                    [CBUUID.UUIDWithString_(VENDOR_SERVICE)]
                )
            )

        if not found:
            print("Could not retrieve the peripheral. Check the UUID from scan.py.")
            AppHelper.stopEventLoop()
            return

        self.peripheral = found[0]
        name = self.peripheral.name() or "(unnamed)"
        print(f"Retrieved {name} -- connecting (no scan needed)...")
        central.connectPeripheral_options_(self.peripheral, None)

    def centralManager_didConnectPeripheral_(self, central, peripheral):
        print("Connected. Discovering services...\n")
        peripheral.setDelegate_(self)
        peripheral.discoverServices_(None)

    def centralManager_didFailToConnectPeripheral_error_(self, central, peripheral, error):
        print(f"Connect failed: {error}")
        AppHelper.stopEventLoop()

    def centralManager_didDisconnectPeripheral_error_(self, central, peripheral, error):
        print(f"\nDisconnected: {error}")
        AppHelper.stopEventLoop()

    # --- peripheral --------------------------------------------------------

    def peripheral_didDiscoverServices_(self, peripheral, error):
        if error:
            print(f"Service discovery failed: {error}")
            return
        services = peripheral.services() or []
        self.pending = len(services)
        for service in services:
            print(f"service {service.UUID()}")
            peripheral.discoverCharacteristics_forService_(None, service)

    def peripheral_didDiscoverCharacteristicsForService_error_(
        self, peripheral, service, error
    ):
        self.pending -= 1
        for char in service.characteristics() or []:
            uuid = str(char.UUID()).upper()
            props = char.properties()
            flags = []
            if props & 0x02:
                flags.append("read")
            if props & 0x04:
                flags.append("write-no-resp")
            if props & 0x08:
                flags.append("write")
            if props & CBCharacteristicPropertyNotify:
                flags.append("notify")
            if props & CBCharacteristicPropertyIndicate:
                flags.append("indicate")
            print(f"  char {uuid}  [{','.join(flags)}]  {LABELS.get(uuid, '')}")

            if props & 0x02 and uuid in LABELS:
                peripheral.readValueForCharacteristic_(char)
            if props & NOTIFY_MASK:
                peripheral.setNotifyValue_forCharacteristic_(True, char)

        if self.pending == 0:
            print("\nSubscribed. Wear the ring and move around. Ctrl-C to stop.\n")

    def peripheral_didUpdateValueForCharacteristic_error_(self, peripheral, char, error):
        if error:
            return
        value = char.value()
        if value is None:
            return
        uuid = str(char.UUID()).upper()
        raw = bytes(value)
        if uuid in LABELS:
            pretty = raw.decode(errors="replace") if len(raw) > 1 else raw[0]
            print(f"       -> {LABELS[uuid]}: {pretty}")
        else:
            print(f"[notify] {uuid}  {len(raw):3d}B  {hexdump(raw)}")

    def peripheral_didUpdateNotificationStateForCharacteristic_error_(
        self, peripheral, char, error
    ):
        if error:
            print(f"  cannot subscribe {char.UUID()}: {error}")


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else RING_UUID
    delegate = Delegate.alloc().initWithTarget_(target)
    manager = CBCentralManager.alloc().initWithDelegate_queue_(delegate, None)
    _ = manager  # keep a strong reference alive for the run loop
    try:
        AppHelper.runConsoleEventLoop(installInterrupt=True)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
