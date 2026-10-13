"""
Thin GPIO layer: real lgpio on the Pi, or a simulator for desk testing.

Run with --sim (or on a machine without lgpio) to use the simulator. The
simulator lets the Setup page toggle the OmniCore input by hand.
"""

import threading


class LgpioBackend:
    simulated = False

    def __init__(self, chip):
        import lgpio
        self._lg = lgpio
        self.h = lgpio.gpiochip_open(chip)
        if self.h < 0:
            raise RuntimeError(f"Could not open GPIO chip {chip}")

    def claim_output(self, pin, level=0):
        self._lg.gpio_claim_output(self.h, pin, level)

    def claim_input_pulldown(self, pin):
        self._lg.gpio_claim_input(self.h, pin, self._lg.SET_PULL_DOWN)

    def write(self, pin, level):
        self._lg.gpio_write(self.h, pin, level)

    def read(self, pin):
        return self._lg.gpio_read(self.h, pin)

    def pwm(self, pin, freq_hz, duty_pct):
        self._lg.tx_pwm(self.h, pin, freq_hz, duty_pct)

    def close(self):
        self._lg.gpiochip_close(self.h)


class SimBackend:
    """In-memory stand-in for lgpio. Records pin levels and PWM settings."""
    simulated = True

    def __init__(self, chip=None):
        self.levels = {}
        self.pwm_hz = {}
        self._lock = threading.Lock()

    def claim_output(self, pin, level=0):
        self.write(pin, level)

    def claim_input_pulldown(self, pin):
        self.write(pin, 0)

    def write(self, pin, level):
        with self._lock:
            self.levels[pin] = level

    def read(self, pin):
        with self._lock:
            return self.levels.get(pin, 0)

    def pwm(self, pin, freq_hz, duty_pct):
        with self._lock:
            if not freq_hz and not self.pwm_hz.get(pin):
                # Real lgpio refuses to cancel PWM that isn't running
                # (LG_BAD_PWM_MICROS); mirror that so tests catch it.
                raise RuntimeError("bad PWM micros (no PWM active on this GPIO)")
            self.pwm_hz[pin] = freq_hz if duty_pct else 0

    def close(self):
        pass


def open_backend(chip, force_sim=False):
    if force_sim:
        return SimBackend()
    try:
        return LgpioBackend(chip)
    except ImportError:
        print("lgpio not found - running in SIMULATION mode")
        return SimBackend()
