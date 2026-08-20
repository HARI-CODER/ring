"""Work out how the accelerometer axes are glued to the physical ring.

The vendor never documented which sensor axis points through the band, so the
orientation view is guesswork until measured. This walks through three known
poses, averages gravity in each, and reports the mapping.

Runs against the already-running bridge, so start that first:

    python bridge.py          # in another terminal
    python calibrate.py
"""

import asyncio
import json
import math

import websockets

WS_URL = "ws://127.0.0.1:8765"
HOLD_SECONDS = 8.0
COUNTS_PER_G = 8192.0

POSES = [
    (
        "flat",
        "Lay the ring FLAT on the table, like a donut lying down.\n"
        "   (gravity will run along the axis through the hole)",
    ),
    (
        "edge",
        "Stand the ring UP on its edge, like a wheel, and hold it there.\n"
        "   (gravity now runs across the band, in the ring's plane)",
    ),
    (
        "worn",
        "Put the ring ON your finger and rest your hand flat, palm down.",
    ),
]

AXES = ["x", "y", "z"]


async def capture(ws, seconds: float) -> tuple[float, float, float] | None:
    """Average the gravity vector over a window, in g."""
    samples: list[tuple[float, float, float]] = []
    try:
        async with asyncio.timeout(seconds):
            async for message in ws:
                data = json.loads(message)
                if data.get("type") == "accel":
                    samples.append(
                        (
                            data["x"] / COUNTS_PER_G,
                            data["y"] / COUNTS_PER_G,
                            data["z"] / COUNTS_PER_G,
                        )
                    )
    except TimeoutError:
        pass
    if not samples:
        return None
    return tuple(sum(s[a] for s in samples) / len(samples) for a in range(3))  # type: ignore[return-value]


async def countdown(seconds: float) -> None:
    for remaining in range(int(seconds), 0, -1):
        print(f"\r   holding... {remaining}s ", end="", flush=True)
        await asyncio.sleep(1)
    print("\r   captured.        ")


async def main() -> None:
    print("Ring axis calibration. Three poses, 8 seconds each.\n")
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"mode": "motion"}))

        results: dict[str, tuple[float, float, float]] = {}
        for key, instruction in POSES:
            print(f"\n>>> {instruction}")
            for remaining in range(5, 0, -1):
                print(f"\r   starting in {remaining}s ", end="", flush=True)
                await asyncio.sleep(1)
            print("\r   measuring now — hold still.")

            vector = await capture(ws, HOLD_SECONDS)
            if vector is None:
                print("   no samples — is the bridge running and the ring awake?")
                return
            results[key] = vector
            magnitude = math.sqrt(sum(v * v for v in vector))
            print(
                f"   x={vector[0]:+.2f}g y={vector[1]:+.2f}g z={vector[2]:+.2f}g"
                f"   |a|={magnitude:.2f}g"
            )

        print("\n=== result ===")

        flat = results["flat"]
        dominant = max(range(3), key=lambda a: abs(flat[a]))
        print(
            f"Ring's axis (through the hole) is sensor {AXES[dominant].upper()}"
            f", sign {'+' if flat[dominant] > 0 else '-'}"
            f"  ({abs(flat[dominant]):.2f}g of 1.00g in that pose)"
        )

        confidence = abs(flat[dominant]) / max(
            1e-6, math.sqrt(sum(v * v for v in flat))
        )
        if confidence < 0.85:
            print(
                "  WARNING: gravity was spread across axes — the ring probably was not\n"
                "  lying flat. Re-run and keep it square to the table."
            )

        in_plane = [AXES[a].upper() for a in range(3) if a != dominant]
        print(f"Band plane is spanned by sensor {in_plane[0]} and {in_plane[1]}.")
        print(f"\nSo in web/lib/ring.ts, orientation() should treat {AXES[dominant].upper()}")
        print("as the ring's normal. Raw vectors for reference:")
        for key, vector in results.items():
            print(f"  {key:5s} x={vector[0]:+.2f} y={vector[1]:+.2f} z={vector[2]:+.2f}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye")
