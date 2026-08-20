/*
 * ring_gestures — act on gestures from the PBL Halo 2 smart ring.
 *
 * Pair with serial_link.py on the Mac:
 *     python bridge.py          # ring -> websocket
 *     python serial_link.py     # websocket -> this board
 *
 * Line protocol, newline-terminated ASCII at 115200 baud:
 *     G:<name>       a gesture was recognised   e.g.  G:Wave Left
 *     HR:<bpm>       heart rate                 e.g.  HR:78
 *     STEPS:<count>  step total                 e.g.  STEPS:210
 *     PING           keepalive, every 5s
 *
 * Because it is plain text you can test the whole sketch without the ring:
 * open the Arduino Serial Monitor at 115200 with "Newline" line ending and
 * type  G:Wave Left  by hand.
 *
 * To add a gesture, add one row to ACTIONS below. Nothing else changes.
 */

const unsigned long BAUD = 115200;

// The link is considered dead if no PING or command arrives for this long.
const unsigned long LINK_TIMEOUT_MS = 12000;

// Serial input buffer. Long enough for any line the sender produces.
const size_t LINE_MAX = 64;
char line[LINE_MAX];
size_t lineLength = 0;

unsigned long lastMessageMs = 0;
bool linkAlive = false;

int heartRate = 0;
long stepCount = 0;

// ---------------------------------------------------------------------------
// Gesture table — this is the part you edit.
// ---------------------------------------------------------------------------

enum ActionKind {
  ACTION_ON,      // drive the pin HIGH and leave it there
  ACTION_OFF,     // drive the pin LOW and leave it there
  ACTION_TOGGLE,  // flip whatever it currently is
  ACTION_PULSE    // HIGH for PULSE_MS, then back to LOW
};

struct GestureAction {
  const char *name;  // must match the name recorded in the web UI, exactly
  int pin;
  ActionKind kind;
};

const GestureAction ACTIONS[] = {
    {"Wave Left", LED_BUILTIN, ACTION_ON},
    {"Wave Right", LED_BUILTIN, ACTION_OFF},
};
const size_t ACTION_COUNT = sizeof(ACTIONS) / sizeof(ACTIONS[0]);

const unsigned long PULSE_MS = 250;

// Output state is tracked per *pin*, not per table row, because several
// gestures can drive the same pin — as Wave Left and Wave Right do here.
const size_t MAX_PINS = ACTION_COUNT;
int trackedPin[MAX_PINS];
bool trackedState[MAX_PINS];
unsigned long pulseUntil[MAX_PINS];
size_t trackedCount = 0;

size_t slotForPin(int pin) {
  for (size_t i = 0; i < trackedCount; i++) {
    if (trackedPin[i] == pin) {
      return i;
    }
  }
  trackedPin[trackedCount] = pin;
  trackedState[trackedCount] = false;
  pulseUntil[trackedCount] = 0;
  return trackedCount++;
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(BAUD);

  for (size_t i = 0; i < ACTION_COUNT; i++) {
    size_t slot = slotForPin(ACTIONS[i].pin);
    pinMode(ACTIONS[i].pin, OUTPUT);
    digitalWrite(ACTIONS[i].pin, LOW);
    trackedState[slot] = false;
  }

  Serial.println("ready: ring_gestures");
}

void applyAction(const GestureAction &action) {
  size_t slot = slotForPin(action.pin);

  switch (action.kind) {
    case ACTION_ON:
      trackedState[slot] = true;
      break;
    case ACTION_OFF:
      trackedState[slot] = false;
      break;
    case ACTION_TOGGLE:
      trackedState[slot] = !trackedState[slot];
      break;
    case ACTION_PULSE:
      trackedState[slot] = true;
      pulseUntil[slot] = millis() + PULSE_MS;
      break;
  }

  digitalWrite(action.pin, trackedState[slot] ? HIGH : LOW);

  Serial.print("gesture ");
  Serial.print(action.name);
  Serial.print(" -> pin ");
  Serial.print(action.pin);
  if (action.kind == ACTION_PULSE) {
    Serial.println(" PULSE");
  } else {
    Serial.println(trackedState[slot] ? " ON" : " OFF");
  }
}

void handleGesture(const char *name) {
  for (size_t i = 0; i < ACTION_COUNT; i++) {
    if (strcmp(ACTIONS[i].name, name) == 0) {
      applyAction(ACTIONS[i]);
      return;
    }
  }

  Serial.print("gesture ");
  Serial.print(name);
  Serial.println(" -> no action mapped");
}

void handleLine(char *text) {
  lastMessageMs = millis();
  if (!linkAlive) {
    linkAlive = true;
    Serial.println("link up");
  }

  if (strcmp(text, "PING") == 0) {
    return;
  }

  // Split on the FIRST ':' only, so a gesture name may contain spaces and
  // even colons — "Wave Left" arrives intact.
  char *separator = strchr(text, ':');
  if (separator == NULL) {
    return;
  }
  *separator = '\0';
  const char *key = text;
  const char *value = separator + 1;

  if (strcmp(key, "G") == 0) {
    handleGesture(value);
  } else if (strcmp(key, "HR") == 0) {
    heartRate = atoi(value);
  } else if (strcmp(key, "STEPS") == 0) {
    stepCount = atol(value);
  }
}

void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\n' || c == '\r') {
      if (lineLength > 0) {
        line[lineLength] = '\0';
        handleLine(line);
        lineLength = 0;
      }
      continue;
    }

    if (lineLength < LINE_MAX - 1) {
      line[lineLength++] = c;
    } else {
      // Overlong line: drop it rather than wrapping into the next one.
      lineLength = 0;
    }
  }
}

void loop() {
  readSerial();

  // End any pulses whose time is up. Deadline arithmetic rather than delay(),
  // so serial input is never stalled and lines are not dropped.
  unsigned long now = millis();
  for (size_t i = 0; i < trackedCount; i++) {
    if (pulseUntil[i] != 0 && (long)(now - pulseUntil[i]) >= 0) {
      trackedState[i] = false;
      digitalWrite(trackedPin[i], LOW);
      pulseUntil[i] = 0;
    }
  }

  // Notice a dead link. The LED is deliberately left as-is: an explicit
  // Wave Left should stay on if the Mac goes away. Drive it LOW here instead
  // if you are switching something that must not stay energised.
  if (linkAlive && (now - lastMessageMs) > LINK_TIMEOUT_MS) {
    linkAlive = false;
    Serial.println("link down");
  }
}
