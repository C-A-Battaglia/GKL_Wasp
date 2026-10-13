"""
Motor control: stepper pulse generation, extruder state machine, feeder.

Speeds are output-shaft RPM everywhere. The GUI never touches GPIO directly.
"""

import threading
import time

from . import config as C
from .config import clamp


def rpm_to_hz(rpm, steps_per_rev):
    return rpm / 60.0 * steps_per_rev


class Stepper:
    def __init__(self, gpio, step_pin, dir_pin, forward, reverse, steps_per_rev):
        self.gpio = gpio
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.forward = forward
        self.reverse = reverse
        self.steps_per_rev = steps_per_rev
        gpio.claim_output(step_pin, 0)
        gpio.claim_output(dir_pin, forward)
        self.running = False

    def set_forward(self):
        self.gpio.write(self.dir_pin, self.forward)

    def set_reverse(self):
        self.gpio.write(self.dir_pin, self.reverse)

    def run(self, rpm):
        hz = clamp(rpm_to_hz(rpm, self.steps_per_rev), 0.1, C.MAX_STEP_HZ)
        self.gpio.pwm(self.step_pin, hz, 50)
        self.running = True

    def stop(self):
        """Safe to call when already stopped. lgpio raises if asked to cancel
        PWM that isn't running, which used to abort RELEASE FEEDER, STOP ALL
        and shutdown part-way through when the motor was idle."""
        try:
            self.gpio.pwm(self.step_pin, 0, 0)
        except Exception:
            if self.running:
                raise           # a real failure to stop a moving motor
        self.gpio.write(self.step_pin, 0)
        self.running = False


class Extruder:
    STOPPED = "STOPPED"
    PRIMING = "PRIMING"
    EXTRUDING = "EXTRUDING"
    RETRACTING = "RETRACTING"

    def __init__(self, gpio, stepper):
        self.gpio = gpio
        self.stepper = stepper
        self.state = self.STOPPED
        self.rpm = C.DEFAULT_PROFILE["ext_rpm"]
        self.retract_s = C.DEFAULT_PROFILE["retract_s"]
        self.prime_s = C.DEFAULT_PROFILE["prime_s"]
        self.manual_override = False   # True: GUI START/STOP drives it, OmniCore ignored
        self.manual_running = False
        self.override_stop = False     # True: hold stopped even though OmniCore is HIGH
        self.omnicore_signal = 0
        self.run_start_time = None
        self.total_run_time = 0.0
        self.alive = True
        self.lock = threading.RLock()
        gpio.claim_input_pulldown(C.EXT_SIGNAL_PIN)

    # ---- settings ----

    def set_rpm(self, rpm):
        with self.lock:
            self.rpm = round(clamp(rpm, C.EXT_MIN_RPM, C.EXT_MAX_RPM), 1)
            if self.state == self.EXTRUDING:
                self.stepper.run(self.rpm)

    def set_retract(self, seconds):
        with self.lock:
            self.retract_s = round(clamp(seconds, C.MIN_RETRACT_PRIME, C.MAX_RETRACT_PRIME), 2)

    def set_prime(self, seconds):
        with self.lock:
            self.prime_s = round(clamp(seconds, C.MIN_RETRACT_PRIME, C.MAX_RETRACT_PRIME), 2)

    # ---- operator commands ----

    def toggle_manual_override(self):
        with self.lock:
            self.manual_override = not self.manual_override
            self.manual_running = False
            self.override_stop = False

    def manual_start_stop(self):
        with self.lock:
            if self.manual_override:
                self.manual_running = not self.manual_running

    def stop_button(self):
        """STOP in manual mode; OVERRIDE STOP toggle when OmniCore is driving."""
        with self.lock:
            if self.manual_override:
                self.manual_running = False
            else:
                self.override_stop = not self.override_stop

    def stop_all(self):
        with self.lock:
            self.manual_running = False
            if not self.manual_override and self.omnicore_signal:
                self.override_stop = True

    def reset_run_time(self):
        with self.lock:
            self.total_run_time = 0.0
            self.run_start_time = time.time() if self.state == self.EXTRUDING else None

    # ---- status ----

    def get_run_time(self):
        with self.lock:
            if self.state == self.EXTRUDING and self.run_start_time:
                return self.total_run_time + (time.time() - self.run_start_time)
            return self.total_run_time

    def should_run(self):
        with self.lock:
            if self.manual_override:
                return self.manual_running
            return self.omnicore_signal == 1 and not self.override_stop

    # ---- control loop (own thread) ----

    def _wait(self, seconds, keep_going):
        end = time.time() + seconds
        while time.time() < end:
            if not self.alive or not keep_going():
                return False
            time.sleep(0.01)
        return True

    def _poll_signal(self):
        with self.lock:
            self.omnicore_signal = self.gpio.read(C.EXT_SIGNAL_PIN)
            if not self.omnicore_signal:
                # An override stop only means something while the robot asks to run.
                self.override_stop = False

    def control_loop(self):
        extruding = False
        while self.alive:
            self._poll_signal()
            want = self.should_run()

            if want and not extruding:
                if self.prime_s > 0:
                    self.state = self.PRIMING
                    self.stepper.set_forward()
                    self.stepper.run(self.rpm)
                    if not self._wait(self.prime_s, lambda: (self._poll_signal(), self.should_run())[1]):
                        self.stepper.stop()
                        self.state = self.STOPPED
                        continue
                with self.lock:
                    self.state = self.EXTRUDING
                    self.stepper.set_forward()
                    self.stepper.run(self.rpm)
                    self.run_start_time = time.time()
                extruding = True

            elif not want and extruding:
                with self.lock:
                    self.stepper.stop()
                    if self.run_start_time:
                        self.total_run_time += time.time() - self.run_start_time
                        self.run_start_time = None
                if self.retract_s > 0:
                    self.state = self.RETRACTING
                    self.stepper.set_reverse()
                    self.stepper.run(self.rpm)
                    self._wait(self.retract_s, lambda: True)
                    self.stepper.stop()
                    self.stepper.set_forward()
                self.state = self.STOPPED
                extruding = False

            time.sleep(0.01)
        self.stepper.stop()

    def shutdown(self):
        self.alive = False


class Feeder:
    IDLE = "IDLE"            # front panel in control
    PI_CONTROL = "PI CTRL"   # Pi holds the relay, motor stopped
    FEEDING = "FEEDING"

    def __init__(self, gpio, stepper, extruder):
        self.gpio = gpio
        self.stepper = stepper
        self.ext = extruder
        self.state = self.IDLE
        self.rpm = C.DEFAULT_PROFILE["feed_rpm"]
        self.pi_has_control = False
        self.feeding = False
        self.linked = False
        self.ratio_locked = False
        self.ratio = C.DEFAULT_PROFILE["ratio"]
        self.baseline_feed_rpm = self.rpm
        self.baseline_ext_rpm = extruder.rpm
        self.alive = True
        self.lock = threading.RLock()
        gpio.claim_output(C.FEED_RELAY_PIN, 0)

    # ---- speed ----

    def set_rpm(self, rpm):
        with self.lock:
            self.rpm = round(clamp(rpm, C.FEED_MIN_RPM, C.FEED_MAX_RPM), 1)
            if self.ratio_locked:
                # A manual feeder change becomes the new baseline.
                self.baseline_feed_rpm = self.rpm
                self.baseline_ext_rpm = self.ext.rpm
            if self.feeding:
                self.stepper.run(self.rpm)

    def follow_extruder(self):
        """With ratio lock on, feeder follows extruder *changes*:
        feed = baseline_feed + (ext - baseline_ext) * ratio"""
        with self.lock:
            if not self.ratio_locked:
                return
            delta = (self.ext.rpm - self.baseline_ext_rpm) * self.ratio
            self.rpm = round(clamp(self.baseline_feed_rpm + delta, C.FEED_MIN_RPM, C.FEED_MAX_RPM), 1)
            if self.feeding:
                self.stepper.run(self.rpm)

    def set_ratio(self, ratio):
        with self.lock:
            self.ratio = round(clamp(ratio, C.MIN_RATIO, C.MAX_RATIO), 2)
            self.follow_extruder()

    def set_ratio_lock(self, on):
        with self.lock:
            self.ratio_locked = on
            if on:
                self.baseline_feed_rpm = self.rpm
                self.baseline_ext_rpm = self.ext.rpm

    # ---- relay / run ----

    def take_control(self):
        with self.lock:
            self.gpio.write(C.FEED_RELAY_PIN, 1)
            self.pi_has_control = True
            self._update_state()

    def release_control(self):
        with self.lock:
            self.stepper.stop()
            self.feeding = False
            self.linked = False
            self.gpio.write(C.FEED_RELAY_PIN, 0)
            self.pi_has_control = False
            self._update_state()

    def start_feeding(self):
        with self.lock:
            if not self.pi_has_control:
                return
            self.stepper.set_forward()
            self.stepper.run(self.rpm)
            self.feeding = True
            self._update_state()

    def stop_feeding(self):
        with self.lock:
            self.stepper.stop()
            self.feeding = False
            self._update_state()

    def set_linked(self, on):
        with self.lock:
            self.linked = on
            if on and not self.pi_has_control:
                self.take_control()

    def stop_all(self):
        """Stop the motor and unlink, but keep the relay so the front
        panel can't restart the feeder on its own."""
        with self.lock:
            self.linked = False
            self.stop_feeding()

    def _update_state(self):
        if self.feeding:
            self.state = self.FEEDING
        elif self.pi_has_control:
            self.state = self.PI_CONTROL
        else:
            self.state = self.IDLE

    # ---- control loop (own thread) ----

    def control_loop(self):
        was_extruding = False
        while self.alive:
            with self.lock:
                linked = self.linked and self.pi_has_control
            if linked:
                ext_on = self.ext.state == Extruder.EXTRUDING
                if ext_on and not was_extruding:
                    self.start_feeding()
                elif not ext_on and was_extruding:
                    self.stop_feeding()
                was_extruding = ext_on
            else:
                was_extruding = False
            time.sleep(0.02)
        self.stepper.stop()
        self.gpio.write(C.FEED_RELAY_PIN, 0)

    def shutdown(self):
        self.alive = False


class Machine:
    """Owns the GPIO backend, both motors and their threads."""

    def __init__(self, gpio):
        self.gpio = gpio
        self.extruder = Extruder(gpio, Stepper(
            gpio, C.EXT_STEP_PIN, C.EXT_DIRECTION_PIN,
            C.EXT_FORWARD, C.EXT_REVERSE, C.EXT_STEPS_PER_OUTPUT_REV))
        self.feeder = Feeder(gpio, Stepper(
            gpio, C.FEED_STEP_PIN, C.FEED_DIRECTION_PIN,
            C.FEED_FORWARD, C.FEED_REVERSE, C.FEED_STEPS_PER_OUTPUT_REV), self.extruder)
        self._threads = []

    @property
    def simulated(self):
        return self.gpio.simulated

    def start(self):
        for target in (self.extruder.control_loop, self.feeder.control_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def set_ext_rpm(self, rpm):
        self.extruder.set_rpm(rpm)
        self.feeder.follow_extruder()

    def stop_all(self):
        self.extruder.stop_all()
        self.feeder.stop_all()

    def apply_profile(self, p, links=True):
        """Load a profile's values. Linking takes the feeder relay, same as
        pressing LINK by hand; nothing starts moving until the extruder runs.
        links=False loads speeds/times only (used at startup)."""
        self.feeder.set_ratio_lock(False)
        self.extruder.set_rpm(p["ext_rpm"])
        self.extruder.set_retract(p["retract_s"])
        self.extruder.set_prime(p["prime_s"])
        self.feeder.set_rpm(p["feed_rpm"])
        self.feeder.set_ratio(p["ratio"])
        if links:
            self.feeder.set_linked(bool(p.get("link")))
            self.feeder.set_ratio_lock(bool(p.get("ratio_lock")))

    def snapshot(self):
        """Current values in profile form (for save / modified check)."""
        return {
            "ext_rpm": self.extruder.rpm,
            "feed_rpm": self.feeder.rpm,
            "ratio": self.feeder.ratio,
            "retract_s": self.extruder.retract_s,
            "prime_s": self.extruder.prime_s,
            "link": self.feeder.linked,
            "ratio_lock": self.feeder.ratio_locked,
        }

    def shutdown(self):
        self.extruder.shutdown()
        self.feeder.shutdown()
        for t in self._threads:
            t.join(timeout=3)
        self.gpio.close()
