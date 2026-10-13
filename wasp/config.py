"""
Hardware and limit constants.

All speeds in this program are output-shaft RPM. The stepper code converts
RPM to step pulses:  steps/s = RPM / 60 * steps_per_output_rev
"""

GPIO_CHIP = 4

# --- Extruder (DM556) ---
EXT_SIGNAL_PIN = 17        # input from OmniCore (on/off)
EXT_STEP_PIN = 18
EXT_DIRECTION_PIN = 27

# --- Continuous feeder (Leadshine) ---
FEED_STEP_PIN = 22
FEED_DIRECTION_PIN = 23
FEED_RELAY_PIN = 24        # HIGH = Pi takes over from the front panel

# --- Motors ---
EXT_STEPS_PER_MOTOR_REV = 200
EXT_MICROSTEPS = 4
EXT_GEARBOX_RATIO = 5.18
EXT_STEPS_PER_OUTPUT_REV = EXT_STEPS_PER_MOTOR_REV * EXT_MICROSTEPS * EXT_GEARBOX_RATIO  # 4144

FEED_STEPS_PER_MOTOR_REV = 200
FEED_MICROSTEPS = 4
FEED_GEARBOX_RATIO = 1.0
FEED_STEPS_PER_OUTPUT_REV = FEED_STEPS_PER_MOTOR_REV * FEED_MICROSTEPS * FEED_GEARBOX_RATIO  # 800

EXT_FORWARD, EXT_REVERSE = 0, 1
FEED_FORWARD, FEED_REVERSE = 0, 1

# lgpio software PWM is limited to 10 kHz, which caps the extruder at
# 10000 / 4144 * 60 = ~144 RPM. (The old 3.0 "speed factor" = 180 RPM
# asked for 12.4 kHz, which lgpio can't produce.)
MAX_STEP_HZ = 10000.0

# --- Speed limits (RPM) ---
EXT_MIN_RPM = 0.1
EXT_MAX_RPM = 140.0
FEED_MIN_RPM = 0.5
FEED_MAX_RPM = 180.0

# --- Retract / prime (seconds) ---
MIN_RETRACT_PRIME = 0.0
MAX_RETRACT_PRIME = 2.0
RETRACT_PRIME_STEP = 0.05

# --- Feed ratio (feeder RPM change per 1 RPM extruder change) ---
MIN_RATIO = 0.5
MAX_RATIO = 20.0
RATIO_STEP = 0.5

# --- Built-in default profile (what the old script started with) ---
DEFAULT_PROFILE = {
    "name": "Lab Default",
    "nozzle": "",
    "ext_rpm": 12.0,       # old speed factor 0.20
    "feed_rpm": 90.0,      # old speed factor 1.50
    "ratio": 1.0,
    "retract_s": 0.50,
    "prime_s": 0.50,
    "link": False,
    "ratio_lock": False,
    "notes": "Safe starting point",
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))
