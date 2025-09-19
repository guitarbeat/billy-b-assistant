import atexit
import random
import threading
import time
from threading import Lock, Thread

import lgpio
import numpy as np

from .config import is_classic_billy
from .constants import (
    DEFAULT_MOTOR_FREQ,
    DEFAULT_HEAD_SPEED,
    DEFAULT_TAIL_SPEED,
    DEFAULT_HEAD_DURATION,
    DEFAULT_TAIL_DURATION,
    DEFAULT_MOTOR_WATCHDOG_INTERVAL,
    DEFAULT_MOTOR_IDLE_TIMEOUT,
    DEFAULT_INTERLUDE_DELAY_MIN,
    DEFAULT_INTERLUDE_DELAY_MAX,
    DEFAULT_TAIL_MOVE_INTERVAL,
)


# === Configuration ===
USE_THIRD_MOTOR = is_classic_billy()

print(f"⚙️ Using third motor: {USE_THIRD_MOTOR}")

# === GPIO Setup ===
h = lgpio.gpiochip_open(0)
FREQ = DEFAULT_MOTOR_FREQ

# Pin mapping
MOUTH_IN1 = 12  # PWM0_CHAN0, pin 32
MOUTH_IN2 = 5  # pin 29
HEAD_IN1 = 13  # PWM0_CHAN1, pin 33
HEAD_IN2 = 6  # pin 31

if (
    USE_THIRD_MOTOR
):  # Note: more than three hardware PWM channels is only a Pi5 feature!
    TAIL_IN1 = 19  # PWM0_CHAN3, pin 35
    TAIL_IN2 = 26  # pin 37

# Claim GPIOs
motor_pins = [MOUTH_IN1, MOUTH_IN2, HEAD_IN1, HEAD_IN2]
if USE_THIRD_MOTOR:
    motor_pins += [TAIL_IN1, TAIL_IN2]

for pin in motor_pins:
    lgpio.gpio_claim_output(h, pin)
    lgpio.gpio_write(h, pin, 0)

# === State ===
_head_tail_lock = Lock()
_motor_watchdog_running = False
_last_flap = 0
_mouth_open_until = 0
_last_rms = 0
head_out = False


# === Motor Helpers ===
def brake_motor(pin1, pin2):
    lgpio.tx_pwm(h, pin1, FREQ, 0)
    lgpio.tx_pwm(h, pin2, FREQ, 0)
    lgpio.gpio_write(h, pin1, 0)
    lgpio.gpio_write(h, pin2, 0)


def run_motor(pwm_pin, low_pin, speed_percent=100, duration=0.3, brake=True):
    lgpio.gpio_write(h, low_pin, 0)
    lgpio.tx_pwm(h, pwm_pin, FREQ, speed_percent)
    time.sleep(duration)
    if brake:
        brake_motor(pwm_pin, low_pin)


# === Movement Functions ===
def move_mouth(speed_percent, duration, brake=False):
    run_motor(MOUTH_IN1, MOUTH_IN2, speed_percent, duration, brake)


def stop_mouth():
    brake_motor(MOUTH_IN1, MOUTH_IN2)


def move_head(state="on"):
    global head_out

    def _move_head_on():
        lgpio.gpio_write(h, HEAD_IN2, 0)
        lgpio.tx_pwm(h, HEAD_IN1, FREQ, DEFAULT_HEAD_SPEED)
        time.sleep(DEFAULT_HEAD_DURATION)
        lgpio.tx_pwm(h, HEAD_IN1, FREQ, 100)  # Stay extended

    if state == "on":
        if not head_out:
            threading.Thread(target=_move_head_on, daemon=True).start()
            head_out = True
    else:
        brake_motor(HEAD_IN1, HEAD_IN2)
        head_out = False


def move_tail(duration=DEFAULT_TAIL_DURATION):
    if USE_THIRD_MOTOR:
        run_motor(TAIL_IN1, TAIL_IN2, speed_percent=DEFAULT_TAIL_SPEED, duration=duration)
    else:
        run_motor(HEAD_IN2, HEAD_IN1, speed_percent=DEFAULT_TAIL_SPEED, duration=duration)


def move_tail_async(duration=0.3):
    threading.Thread(target=move_tail, args=(duration,), daemon=True).start()


# === Mouth Sync ===
def flap_from_pcm_chunk(
    audio, threshold=1500, min_flap_gap=0.1, chunk_ms=40, sample_rate=24000
):
    global _last_flap, _mouth_open_until, _last_rms
    now = time.time()

    if audio.size == 0:
        return

    rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
    peak = np.max(np.abs(audio))

    # Smooth out sudden fluctuations
    if '_last_rms' not in globals():
        _last_rms = rms
    alpha = 1  # smoothing factor
    rms = alpha * rms + (1 - alpha) * _last_rms
    _last_rms = rms

    # If too quiet and mouth might be open, stop motor
    if rms < threshold / 2 and now >= _mouth_open_until:
        stop_mouth()
        return

    if rms <= threshold or (now - _last_flap) < min_flap_gap:
        return

    normalized = np.clip(rms / 32768.0, 0.0, 1.0)
    dyn_range = peak / (rms + 1e-5)

    # Flap speed and duration scaling
    speed = int(np.clip(np.interp(normalized, [0.005, 0.15], [25, 100]), 25, 100))
    duration_ms = np.interp(normalized, [0.005, 0.15], [15, 70])

    duration_ms = np.clip(duration_ms, 15, chunk_ms)
    duration = duration_ms / 1000.0

    _last_flap = now
    _mouth_open_until = now + duration

    move_mouth(speed, duration, brake=False)


# === Interlude Behavior ===
def _interlude_routine():
    try:
        move_head("off")
        time.sleep(random.uniform(DEFAULT_INTERLUDE_DELAY_MIN, DEFAULT_INTERLUDE_DELAY_MAX))

        flap_count = random.randint(1, 3)
        for _ in range(flap_count):
            move_tail()
            time.sleep(random.uniform(0.25, 0.9))

        if random.random() < 0.9:
            move_head("on")
    except Exception as e:
        print(f"⚠️ Interlude error: {e}")


def interlude():
    """Run head/tail interlude in a background thread if not already running."""
    if _head_tail_lock.locked():
        return
    Thread(target=lambda: _interlude_routine(), daemon=True).start()


# === Motor Watchdog ===
def stop_all_motors():
    print("🛑 Stopping all motors")
    move_head("off")
    for pin in motor_pins:
        lgpio.tx_pwm(h, pin, FREQ, 0)
        lgpio.gpio_write(h, pin, 0)


def is_motor_active():
    return any(lgpio.gpio_read(h, pin) == 1 for pin in motor_pins)


def motor_watchdog():
    """Background thread that stops motors if active too long."""
    global _motor_watchdog_running
    _motor_watchdog_running = True
    last_activity = time.time()
    idle = True
    while _motor_watchdog_running:
        active = is_motor_active()
        now = time.time()

        if active:
            last_activity = now
            idle = False
        elif not idle and now - last_activity > DEFAULT_MOTOR_IDLE_TIMEOUT:
            stop_all_motors()
            idle = True
        time.sleep(DEFAULT_MOTOR_WATCHDOG_INTERVAL)


def start_motor_watchdog():
    Thread(target=motor_watchdog, daemon=True).start()


def stop_motor_watchdog():
    global _motor_watchdog_running
    _motor_watchdog_running = False


atexit.register(stop_all_motors)
atexit.register(stop_motor_watchdog)
