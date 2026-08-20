.venv/bin/python bridge.py            
.venv/bin/python serial_link.py --port /dev/cu.usbserial-10 --echo 
to open the web ui ----- cd web && npm run dev                 # terminal 2 → localhost:3000



# PBL Halo 2 — sensor access from macOS

Working client for the `PBL Halo 2_6600` smart ring. Battery and live heart rate
are confirmed working.

```sh
python3 -m venv .venv && .venv/bin/pip install bleak   # pulls in pyobjc CoreBluetooth

.venv/bin/python ring.py battery   # -> Battery: 90%  (not charging)
.venv/bin/python ring.py hr        # -> heart rate: 92 bpm, once per second
.venv/bin/python ring.py spo2      # -> live blood oxygen
.venv/bin/python ring.py raw       # dump every frame, decode nothing

.venv/bin/python imu.py            # -> accelerometer X/Y/Z + magnitude in g
.venv/bin/python imu.py --raw      # also show raw PPG channels
```

## Why the ring is invisible to Bluetooth settings and to scanning

Two separate things were going on:

1. It is a **BLE (GATT) peripheral**. Bluetooth control panels list classic
   devices plus a few BLE profiles, so rings and HR straps never show up as
   something you "add". You talk to them from code.
2. macOS had **already connected to it** at the OS level. A BLE peripheral stops
   advertising the moment a central connects, so `scan.py` found nothing even
   though the ring was sitting right there in the Bluetooth menu.

The fix for (2) is *not* to unpair. CoreBluetooth lets any app attach to an
already-connected peripheral with `retrievePeripheralsWithIdentifiers:` — no
scan involved. bleak has no API for this, which is why `ring.py` and
`connect_paired.py` drive CoreBluetooth through pyobjc directly.

## Protocol

Colmi R02 family, over Nordic UART (`6E400002` write / `6E400003` notify).
Fixed 16-byte frames:

```
byte  0     command
bytes 1-14  payload
byte  15    checksum = sum(bytes[0:15]) & 0xFF
```

Commands in use: `0x03` battery, `0x69` start real-time reading
(payload `[kind, 1]`, kind 1 = heart rate, 2 = SpO2), `0x1E` keepalive,
`0x6A` stop. The ring stops streaming unless the keepalive is sent every few
seconds; replies arrive as `0x69 [kind] [err] [value]`.

### Raw sensors (0xA1) — found by probing, not documented

`0xA1` with payload `[subtype, 1]` starts a raw stream, `[subtype, 0]` stops it.
The ring then emits a repeating triplet:

```
a1 01 <u16 be>          PPG channel A, raw optical counts
a1 02 <u16 be>          PPG channel B (0x7FFF = saturated / no skin contact)
a1 03 <i16 i16 i16>     accelerometer X, Y, Z, big-endian signed
```

Accel scale is **8192 counts/g** (+/-4g). Verified: with the ring at rest the
vector magnitude reads 0.94-1.08 g, centred on 1.00.

Subtype (1-6) does not appear to select the sensor — any subtype starts the same
combined stream. Higher subtypes add extra non-zero fields to the `a1 01`/`a1 02`
frames whose meaning is not worked out. Subtype 5 alone produced nothing.

The unsolicited `0x73` frames are a separate always-on activity stream with
steadily incrementing counters (step/timer accumulators); not decoded yet.

**Known limitation:** the accel stream arrives at only ~1 Hz, which is fine for
orientation and coarse motion but too slow for gesture recognition. Whether a
faster rate can be requested is unresolved.

Because this is the Colmi R02 protocol, the open-source
[`colmi_r02_client`](https://github.com/tahnok/colmi_r02_client) is a good
reference for the commands not implemented here (steps, sleep, historical logs).

## Dashboard

Two processes. The browser cannot reach the ring itself — Web Bluetooth needs a
scan to pick a device, and the ring does not advertise while macOS holds it — so
`bridge.py` keeps the CoreBluetooth connection and pushes JSON over a WebSocket.

```sh
.venv/bin/python bridge.py          # terminal 1 - ws://127.0.0.1:8765
cd web && npm install && npm run dev # terminal 2 - http://localhost:3000
```

The page shows a heart beating at the measured BPM, the ring tilting with the
gravity vector, a figure walking at the measured cadence, and live accelerometer
and PPG traces.

### One sensor at a time

The ring will not run heart rate and the raw stream together — with the raw
stream active, heart-rate replies never arrive. So the bridge time-slices
between an `hr` window and a `motion` window, and the UI can pin either.

Two timing constraints, both found the hard way:

- Heart rate needs ~25s of **uninterrupted** measurement to produce a reading,
  and re-issuing the start command restarts that acquisition. Send start once on
  entering the mode, then only the `0x1E` keepalive. `MODE_WINDOW_SECONDS` is 45
  so a window can actually complete.
- The raw stream is the opposite: it lapses unless re-armed every few seconds.

### Message schema

```
battery  {percent, charging}
hr       {bpm}
spo2     {percent}
accel    {x, y, z, g}            raw counts + magnitude in g
ppg      {channel: "a"|"b", value, saturated}
activity {steps, distance_cm, calories}
mode     {mode: "hr"|"motion", pinned}
```

Send `{"mode": "hr" | "motion" | "auto"}` to pin or release the sensor.

## Gestures

Record a named motion (draw an "O", "Z", "I" in the air), then have it
recognised when you repeat it. Pick **gesture** mode in the UI, type a name, hit
Record, and perform the motion. Record each gesture **at least 3 times** — one
example matches poorly.

Stored in `gestures.json` next to the code, so they survive restarts.

### Sample rate: the thing that decides whether this works

A gesture lasts 1-2 seconds. The pushed stream runs at ~1 Hz, which is 1-2
samples — no shape to recognise. Twelve candidate payloads were tried
(`rate.py`); none raised it.

What does work is **polling**: every `0xA1` start command returns a sample
immediately, so re-issuing it every 100ms lifts the reply rate to ~10 Hz
(`poll.py`). Gesture mode does exactly this.

Confirmed with the ring in motion: the polled samples are genuinely fresh, not a
cached value repeated.

```
polls sent      : 116
accel replies   : 116  ->  9.7 Hz
distinct values : 113  ->  9.4 Hz of real motion data
```

So a 1.5s gesture yields ~15 real samples, which is enough to recognise a shape.
(A stationary ring reports ~0 Hz fresh, because an accelerometer at rest really
does return the same numbers — don't read that as a fault.)

The bridge publishes both figures continuously and the UI shows them
(`9.5 Hz polled · 0.2 Hz fresh`), so a regression here is visible rather than
silent. Re-check any time with:

```sh
.venv/bin/python poll.py 100     # move the ring for the 12s it runs
```

### How matching works

Each captured motion is normalised — zero-mean, unit-scale, resampled to 24
points — which removes where your hand was, how hard you moved, and how fast you
drew it. Candidates are compared by **dynamic time warping**, which tolerates
speed differences and very short sequences.

A match must clear two bars: an absolute distance (`ACCEPT_DISTANCE`) and a
margin over the runner-up (`AMBIGUITY_RATIO`). Failing either reports nothing
rather than guessing. Both are in `gestures.py` — raise the first if real
gestures are missed, lower it if unrelated motion gets matched.

Validated on synthetic O/I/Z shapes at 10-22 samples: 24/24 correct, 8/8 noise
rejected. End-to-end through the bridge: 6/6 correct with a spurious segment
properly rejected. Real hand motion is the remaining test — the sample rate it
needs is confirmed, the thresholds are first guesses.

Segmentation thresholds, also in `gestures.py`, decide when a gesture starts and
stops. If short gestures get cut off, raise `QUIET_SECONDS`; if the capture never
triggers, lower `START_G`.

### Improving accuracy

**Record the same name repeatedly** — examples accumulate, and the chip in the UI
shows the count. Three is the working minimum, five is better. This also feeds
the learned threshold below.

**Diagnose before tuning.** This is the tool to reach for when matching is poor:

```sh
.venv/bin/python gestures.py
```

It reports leave-one-out accuracy over what you have recorded, which gestures get
mistaken for which, and how far apart each pair sits relative to how much your own
repeats vary. That distinguishes the two causes of bad accuracy, which need
opposite fixes:

- *One gesture is recorded sloppily* → delete it and re-record more carefully.
- *Two gestures are genuinely alike* → redesign one. No amount of extra examples
  separates shapes the sensor cannot tell apart.

Four things make matching better than a naive nearest-template approach:

1. **Pre-roll.** The 5 samples before the motion trigger are kept, so the gentle
   opening stroke — often the most distinctive part — is not clipped off.
2. **Learned per-gesture thresholds.** A gesture you repeat precisely gets a
   tight accept distance; a sloppy one gets a loose one. Replaces a single
   global guess (`threshold()`).
3. **Two-closest scoring.** A candidate is scored against the mean of a
   gesture's two nearest examples, not its single nearest, so one bad recording
   cannot drag every match toward it.
4. **Outlier warning on save.** A new example far from its siblings is flagged
   in the UI rather than silently poisoning the set.

On a miss the UI lists the top three distances against each gesture's threshold,
so you can see whether it was close or nowhere near.

**Designing gestures that work.** The ring measures acceleration, not position —
it sees the force profile of the motion, not the traced path. Shapes separate
well when their *acceleration* differs: a large slow circle (smooth, continuous
turning) against a "Z" (three sharp reversals) against a single straight sweep.
Two shapes drawn with similar corner-and-speed patterns will collide however
different they look written down.

## Arduino over serial

Three processes; the Arduino is the last hop.

```sh
.venv/bin/python bridge.py        # terminal 1 - ring -> websocket
.venv/bin/python serial_link.py   # terminal 2 - websocket -> serial
cd web && npm run dev             # terminal 3 - optional, for recording gestures
```

Upload `arduino/ring_gestures/ring_gestures.ino` first. The port is auto-detected;
override with `--port`, and use `--echo` to see what the board prints back.

```sh
.venv/bin/python serial_link.py --list                    # candidate ports
.venv/bin/python serial_link.py --port /dev/cu.usbserial-10 --echo
```

### Wire protocol

Newline-terminated ASCII at **115200 baud** (the sketch and `serial_link.py` must
agree — a mismatch shows up as garbage, not silence).

```
G:<name>       a gesture was recognised     G:O
HR:<bpm>       heart rate                   HR:78
STEPS:<count>  step total                   STEPS:210
PING           keepalive every 5s
```

Plain text on purpose: you can drive the sketch by hand from the Arduino Serial
Monitor (115200, line ending "Newline") by typing `G:O`, with no ring involved.
That separates "is my wiring right" from "is my gesture being recognised".

### Mapping gestures to pins

One row per gesture in the sketch's table; nothing else changes.

```c
const GestureAction ACTIONS[] = {
    {"Wave Left", LED_BUILTIN, ACTION_ON},
    {"Wave Right", LED_BUILTIN, ACTION_OFF},
};
```

Four kinds: `ACTION_ON`, `ACTION_OFF`, `ACTION_TOGGLE`, `ACTION_PULSE`. Several
gestures may drive the same pin — output state is tracked per pin, not per row,
so on/off pairs like the above behave correctly.

The name must match what you recorded in the web UI **exactly, including case and
spaces**: `Wave Left` matches, `wave left` does not. Names with spaces are fine —
the protocol splits on the first `:` only.

### Behaviour worth knowing

- **Stale gestures are dropped.** The bridge replays the last event of each type
  to a newly connected client. That is right for heart rate but would re-fire an
  action on reconnect, so gestures older than `STALE_SECONDS` are ignored.
- **Repeats are debounced.** One physical motion can produce two recognitions;
  the same gesture inside `GESTURE_COOLDOWN` is sent once.
- **Pulses do not block.** The sketch uses `millis()` deadlines rather than
  `delay()`, so serial input is never stalled and lines are not dropped.
- **The board notices a dead link.** No traffic for 12s prints `link down`. The
  LED is deliberately *left as it is* — an explicit "Wave Left" should stay on if
  the Mac goes away. Drive the pin LOW in that branch if you switch something
  that must not stay energised.
- **Opening the port resets most Arduinos**, so `serial_link.py` waits 2s before
  sending anything.
- Unplugging the board is survivable: the link reopens when it reappears.

## Files

- `bridge.py` — BLE -> WebSocket bridge that feeds the dashboard
- `serial_link.py` — WebSocket -> Arduino over USB serial
- `arduino/ring_gestures/` — the sketch that acts on gestures
- `web/` — Next.js + TypeScript dashboard
- `ring.py` — battery / heart rate / SpO2 client
- `imu.py` — accelerometer + raw PPG stream
- `explore.py` — protocol prober; sweeps candidate commands, watches all
  notify channels at once. Keep probes targeted: unknown opcodes in this family
  include factory-reset / unbind / DFU.
- `scan.py` — BLE scan, only works when nothing else holds the ring
- `connect_paired.py` — full GATT tree dump + raw notification firehose
