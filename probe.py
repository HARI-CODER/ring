"""Connect to the ring, dump its GATT tree, then subscribe to every notify
characteristic and print whatever it pushes.

Usage:
    python probe.py                 # match by name substring "halo"
    python probe.py "PBL Halo"      # match a different name
    python probe.py <uuid-or-mac>   # connect directly by address
"""

import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

# Well-known vendor service used by most of these rings.
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # ring -> host (notify)
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # host -> ring (write)

READABLE_STD = {  # standard characteristics worth reading once
    "00002a19-0000-1000-8000-00805f9b34fb": "Battery Level",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Rev",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Rev",
    "00002a28-0000-1000-8000-00805f9b34fb": "Software Rev",
}


async def find(target: str):
    if "-" in target and len(target) == 36 or ":" in target:
        return target
    print(f"Looking for a device whose name contains {target!r} ...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, adv: target.lower() in ((adv.local_name or d.name or "").lower()),
        timeout=20.0,
    )
    if device is None:
        sys.exit(f"Not found. Is it still connected to the phone app?")
    print(f"Found {device.name} @ {device.address}")
    return device


def on_packet(label: str):
    start = time.monotonic()

    def handler(_sender, data: bytearray) -> None:
        print(f"[{time.monotonic() - start:7.2f}s] {label} {len(data):3d}B  {data.hex(' ')}")

    return handler


async def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "halo"
    device = await find(target)

    async with BleakClient(device, timeout=30.0) as client:
        print(f"\nConnected. MTU={client.mtu_size}\n")

        notifiables = []
        for service in client.services:
            print(f"service {service.uuid}  {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  char {char.uuid}  [{props}]  {char.description}")
                if "read" in char.properties and char.uuid in READABLE_STD:
                    try:
                        raw = await client.read_gatt_char(char)
                        pretty = raw.decode(errors="replace") if len(raw) > 1 else raw[0]
                        print(f"       -> {READABLE_STD[char.uuid]}: {pretty}")
                    except Exception as exc:  # noqa: BLE001
                        print(f"       -> read failed: {exc}")
                if "notify" in char.properties or "indicate" in char.properties:
                    notifiables.append(char)

        print(f"\nSubscribing to {len(notifiables)} notify characteristic(s)...")
        for char in notifiables:
            try:
                await client.start_notify(char, on_packet(char.uuid[:8]))
            except Exception as exc:  # noqa: BLE001
                print(f"  cannot subscribe {char.uuid}: {exc}")

        print("Listening. Move your hand / wear the ring. Ctrl-C to stop.\n")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye")
