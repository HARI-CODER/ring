"""Scan for BLE peripherals and highlight likely smart-ring candidates."""

import asyncio
import sys

from bleak import BleakScanner

HINTS = ("halo", "pebble", "ring", "r02", "colmi", "qring")


async def main(seconds: float = 12.0) -> None:
    print(f"Scanning {seconds:.0f}s ... (keep the ring off the charger, awake)\n")
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)

    rows = []
    for device, adv in found.values():
        name = adv.local_name or device.name or ""
        rows.append((adv.rssi, name, device.address, adv.service_uuids, adv.manufacturer_data))

    rows.sort(key=lambda r: -r[0])
    for rssi, name, address, uuids, mfr in rows:
        hit = any(h in name.lower() for h in HINTS)
        print(f"{'>>' if hit else '  '} {rssi:4d} dBm  {name or '(no name)':<28} {address}")
        if hit:
            print(f"       services: {uuids or '(none advertised)'}")
            print(f"       mfr data: { {k: v.hex() for k, v in mfr.items()} or '(none)'}")

    if not any(any(h in r[1].lower() for h in HINTS) for r in rows):
        print("\nNo ring-like name seen. It is probably still connected to the phone app.")


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 12.0))
