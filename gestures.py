"""Gesture segmentation, storage and recognition for the ring.

Design constraints that shaped this:

* Samples arrive at ~10 Hz (polled). A gesture is therefore only a couple of
  dozen points, so the matcher must tolerate very short sequences.
* People never draw the same shape at the same speed or size twice. So each
  candidate is scale- and speed-normalised, and compared with dynamic time
  warping, which stretches one sequence onto the other.
* No numpy dependency: sequences are tiny and the cost is negligible.

Run this file directly to score the gestures you have already recorded:

    python gestures.py        # leave-one-out accuracy + which pairs collide
"""

from __future__ import annotations

import json
import math
import os
from collections import deque
from dataclasses import dataclass, field

STORE_PATH = os.path.join(os.path.dirname(__file__), "gestures.json")

# --- segmentation ----------------------------------------------------------

START_G = 0.30  # motion above this (deviation from 1g rest) opens a gesture
STOP_G = 0.18  # falling below this for QUIET_SECONDS closes it
QUIET_SECONDS = 0.55
MIN_SAMPLES = 6
MIN_SECONDS = 0.35
MAX_SECONDS = 5.0
# Samples kept before the trigger fires. Without this the gentle start of a
# gesture is cut off, and the first stroke is exactly what distinguishes many
# shapes from each other.
PREROLL_SAMPLES = 5

# --- matching --------------------------------------------------------------

RESAMPLE_TO = 24
# Fallback accept distance, used only for a gesture with a single example.
# With two or more examples the threshold is learned from the examples instead.
DEFAULT_ACCEPT = 0.95
ACCEPT_FLOOR = 0.35  # never demand a tighter match than this
ACCEPT_CEILING = 1.30  # never accept a looser one than this
# The best match must beat the runner-up by this ratio, else it is ambiguous.
AMBIGUITY_RATIO = 0.85

Vector = tuple[float, float, float]


def _resample(points: list[Vector], count: int) -> list[Vector]:
    """Linear resample to a fixed length so DTW sees comparable sequences."""
    if len(points) == 1:
        return [points[0]] * count
    out: list[Vector] = []
    for i in range(count):
        position = i * (len(points) - 1) / (count - 1)
        low = int(math.floor(position))
        high = min(low + 1, len(points) - 1)
        frac = position - low
        out.append(
            tuple(points[low][axis] * (1 - frac) + points[high][axis] * frac for axis in range(3))  # type: ignore[misc]
        )
    return out


def normalise(points: list[Vector]) -> list[Vector]:
    """Zero-mean, unit-scale, fixed-length — removes orientation offset, how
    hard you moved, and how fast you drew it."""
    if not points:
        return []
    resampled = _resample(points, RESAMPLE_TO)
    means = [sum(p[a] for p in resampled) / len(resampled) for a in range(3)]
    centred = [tuple(p[a] - means[a] for a in range(3)) for p in resampled]
    # One shared scale across axes, so the shape's proportions survive.
    scale = math.sqrt(sum(sum(c[a] ** 2 for a in range(3)) for c in centred) / len(centred))
    if scale < 1e-6:
        return [(0.0, 0.0, 0.0)] * RESAMPLE_TO
    return [tuple(c[a] / scale for a in range(3)) for c in centred]  # type: ignore[misc]


def dtw(a: list[Vector], b: list[Vector]) -> float:
    """Mean per-step DTW distance between two normalised sequences."""
    if not a or not b:
        return float("inf")
    inf = float("inf")
    previous = [inf] * (len(b) + 1)
    previous[0] = 0.0
    for i in range(1, len(a) + 1):
        current = [inf] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            cost = math.dist(a[i - 1], b[j - 1])
            current[j] = cost + min(previous[j], current[j - 1], previous[j - 1])
        previous = current
    # Normalise by path length so long and short gestures compare fairly.
    return previous[len(b)] / (len(a) + len(b))


def _score(candidate: list[Vector], examples: list[list[Vector]]) -> float:
    """Distance from a candidate to a gesture's example set.

    Mean of the two closest examples rather than the single closest, so one
    sloppy recording cannot drag every match toward its gesture.
    """
    distances = sorted(dtw(candidate, example) for example in examples)
    if not distances:
        return float("inf")
    return sum(distances[:2]) / len(distances[:2])


@dataclass
class Store:
    """Named gestures, each with one or more recorded examples."""

    templates: dict[str, list[list[Vector]]] = field(default_factory=dict)

    def load(self) -> "Store":
        if os.path.exists(STORE_PATH):
            with open(STORE_PATH) as handle:
                raw = json.load(handle)
            self.templates = {
                name: [[tuple(p) for p in example] for example in examples]  # type: ignore[misc]
                for name, examples in raw.items()
            }
        return self

    def save(self) -> None:
        with open(STORE_PATH, "w") as handle:
            json.dump(
                {
                    name: [[list(p) for p in ex] for ex in examples]
                    for name, examples in self.templates.items()
                },
                handle,
                indent=1,
            )

    def add(self, name: str, points: list[Vector]) -> dict:
        """Store an example, and report how well it agrees with the others.

        A new example that sits far from its siblings is usually a botched
        capture, and silently keeping it poisons every future match.
        """
        candidate = normalise(points)
        existing = self.templates.get(name, [])
        agreement = (
            min((dtw(candidate, other) for other in existing), default=None) if existing else None
        )
        self.templates.setdefault(name, []).append(candidate)
        self.save()
        return {
            "examples": len(self.templates[name]),
            "agreement": round(agreement, 3) if agreement is not None else None,
            "outlier": agreement is not None and agreement > ACCEPT_CEILING,
        }

    def delete(self, name: str) -> None:
        self.templates.pop(name, None)
        self.save()

    def summary(self) -> list[dict]:
        return [
            {"name": name, "examples": len(ex), "threshold": round(self.threshold(name), 3)}
            for name, ex in sorted(self.templates.items())
        ]

    def threshold(self, name: str) -> float:
        """Accept distance learned from how consistently *you* draw this one.

        A gesture you repeat precisely gets a tight threshold; a sloppy one gets
        a loose threshold automatically, instead of a single global guess.
        """
        examples = self.templates.get(name, [])
        if len(examples) < 2:
            return DEFAULT_ACCEPT
        spreads = [
            min(dtw(examples[i], examples[j]) for j in range(len(examples)) if j != i)
            for i in range(len(examples))
        ]
        mean = sum(spreads) / len(spreads)
        variance = sum((s - mean) ** 2 for s in spreads) / len(spreads)
        return max(ACCEPT_FLOOR, min(ACCEPT_CEILING, mean + 2 * math.sqrt(variance)))

    def rank(self, points: list[Vector]) -> list[dict]:
        """Every gesture scored against a candidate, closest first."""
        candidate = normalise(points)
        ranked = [
            {
                "name": name,
                "distance": round(_score(candidate, examples), 3),
                "threshold": round(self.threshold(name), 3),
            }
            for name, examples in self.templates.items()
        ]
        ranked.sort(key=lambda r: r["distance"])
        return ranked

    def match(self, points: list[Vector]) -> dict:
        """Nearest template, with a learned threshold and an ambiguity guard."""
        ranked = self.rank(points)
        if not ranked:
            return {"name": None, "reason": "no gestures recorded", "ranking": []}

        best = ranked[0]
        runner_up = ranked[1]["distance"] if len(ranked) > 1 else float("inf")
        common = {"distance": best["distance"], "ranking": ranked[:3]}

        if best["distance"] > best["threshold"]:
            return {"name": None, "reason": "no close match", **common}
        if best["distance"] > runner_up * AMBIGUITY_RATIO:
            return {
                "name": None,
                "reason": f"ambiguous ({best['name']} vs {ranked[1]['name']})",
                **common,
            }
        return {"name": best["name"], "reason": None, **common}

    def evaluate(self) -> dict:
        """Leave-one-out check over the recorded examples.

        Answers the question that actually matters when accuracy is poor: is a
        gesture badly recorded, or are two gestures simply too alike?
        """
        total = 0
        correct = 0
        confusion: dict[str, dict[str, int]] = {}

        for name, examples in self.templates.items():
            if len(examples) < 2:
                continue
            for index, held_out in enumerate(examples):
                rest = {
                    other: ([e for i, e in enumerate(ex) if not (other == name and i == index)])
                    for other, ex in self.templates.items()
                }
                rest = {k: v for k, v in rest.items() if v}
                probe = Store(templates=rest)
                # held_out is already normalised, so score directly.
                ranked = [
                    {"name": other, "distance": _score(held_out, ex)}
                    for other, ex in rest.items()
                ]
                ranked.sort(key=lambda r: r["distance"])
                got = ranked[0]["name"] if ranked else None
                if got == name:
                    correct += 1
                else:
                    confusion.setdefault(name, {}).setdefault(str(got), 0)
                    confusion[name][str(got)] += 1
                total += 1
                _ = probe

        return {"total": total, "correct": correct, "confusion": confusion}

    def separations(self) -> list[dict]:
        """Closest distance between each pair of gestures.

        Judged against how much each gesture varies internally, not an absolute
        number: two gestures are a problem when they sit closer to each other
        than your own repeats of them do.
        """
        names = sorted(self.templates)
        out = []
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                distance = min(dtw(x, y) for x in self.templates[a] for y in self.templates[b])
                spread = max(self.threshold(a), self.threshold(b))
                out.append(
                    {
                        "pair": f"{a} vs {b}",
                        "distance": round(distance, 3),
                        "spread": round(spread, 3),
                        "too_similar": distance < spread,
                    }
                )
        out.sort(key=lambda r: r["distance"])
        return out


class Segmenter:
    """Turns a stream of accel samples into discrete gesture candidates.

    Feed it (timestamp, x, y, z) in g. It returns a completed gesture's points
    when motion starts and then settles, otherwise None.
    """

    def __init__(self) -> None:
        self.buffer: list[tuple[float, Vector]] = []
        self.preroll: deque = deque(maxlen=PREROLL_SAMPLES)
        self.active = False
        self.quiet_since: float | None = None

    def feed(self, t: float, x: float, y: float, z: float) -> list[Vector] | None:
        energy = abs(math.sqrt(x * x + y * y + z * z) - 1.0)

        if not self.active:
            self.preroll.append((t, (x, y, z)))
            if energy > START_G:
                self.active = True
                self.quiet_since = None
                # Start from the pre-roll so the gesture's opening stroke, which
                # is below the trigger threshold, is not thrown away.
                self.buffer = list(self.preroll)
            return None

        self.buffer.append((t, (x, y, z)))

        if energy > STOP_G:
            self.quiet_since = None
        elif self.quiet_since is None:
            self.quiet_since = t

        duration = t - self.buffer[0][0]
        settled = self.quiet_since is not None and t - self.quiet_since >= QUIET_SECONDS

        if settled or duration >= MAX_SECONDS:
            points = [p for _, p in self.buffer]
            long_enough = len(points) >= MIN_SAMPLES and duration >= MIN_SECONDS
            self.reset()
            return points if long_enough else None
        return None

    def reset(self) -> None:
        self.buffer = []
        self.preroll.clear()
        self.active = False
        self.quiet_since = None


def _report() -> None:
    store = Store().load()
    if not store.templates:
        print("No gestures recorded yet.")
        return

    print("Recorded gestures")
    for item in store.summary():
        flag = "  <- record more examples" if item["examples"] < 3 else ""
        print(f"  {item['name']:<12} {item['examples']} examples   accept<{item['threshold']}{flag}")

    result = store.evaluate()
    if result["total"]:
        pct = 100 * result["correct"] / result["total"]
        print(f"\nLeave-one-out accuracy: {result['correct']}/{result['total']}  ({pct:.0f}%)")
        for name, got in result["confusion"].items():
            for other, count in got.items():
                print(f"  {name} mistaken for {other}: {count}x")
    else:
        print("\nNeed at least 2 examples of a gesture to score accuracy.")

    pairs = store.separations()
    if pairs:
        print("\nHow far apart the gestures are, vs how much each one varies")
        for pair in pairs:
            warn = "  <- closer than your own repeats; redesign one" if pair["too_similar"] else ""
            print(f"  {pair['pair']:<24} {pair['distance']:<6} (spread {pair['spread']}){warn}")


if __name__ == "__main__":
    _report()
