#!/usr/bin/env python3
"""
WASP Clay Extruder + Continuous Feeder Controller
===================================================
Raspberry Pi 5 - Dual Stepper Control System
University of Houston - CraftLab

Design inspired by Impact dashboard aesthetic.
Light background, dark controls, orange accents.

GPIO Pin Mapping:
  Extruder (DM556):
  - GPIO 17: Digital input from OmniCore (on/off signal)
  - GPIO 18: Step pulse output to DM556
  - GPIO 27: Direction output to DM556

  Continuous Feeder (Leadshine):
  - GPIO 22: Step pulse output to feeder driver
  - GPIO 23: Direction output to feeder driver
  - GPIO 24: Relay control output (Pi takeover from front panel)
"""

import tkinter as tk
import threading
import time
import lgpio

# ============================================================
# CONFIGURATION
# ============================================================

GPIO_CHIP = 4

# --- Extruder GPIO ---
EXT_SIGNAL_PIN = 17
EXT_STEP_PIN = 18
EXT_DIRECTION_PIN = 27

# --- Feeder GPIO ---
FEED_STEP_PIN = 22
FEED_DIRECTION_PIN = 23
FEED_RELAY_PIN = 24

# --- Extruder Motor ---
EXT_STEPS_PER_MOTOR_REV = 200
EXT_MICROSTEPS = 4
EXT_GEARBOX_RATIO = 5.18
EXT_STEPS_PER_OUTPUT_REV = EXT_STEPS_PER_MOTOR_REV * EXT_MICROSTEPS * EXT_GEARBOX_RATIO

# --- Feeder Motor ---
FEED_STEPS_PER_MOTOR_REV = 200
FEED_MICROSTEPS = 4
FEED_GEARBOX_RATIO = 1.0
FEED_STEPS_PER_OUTPUT_REV = FEED_STEPS_PER_MOTOR_REV * FEED_MICROSTEPS * FEED_GEARBOX_RATIO

# --- Speed ---
MIN_SPEED_FACTOR = 0.10
MAX_SPEED_FACTOR = 3.00
SPEED_INCREMENT = 0.01
DEFAULT_EXT_SPEED = 0.20
DEFAULT_FEED_SPEED = 1.50

# --- Retraction/Prime ---
DEFAULT_RETRACT_DURATION = 0.50
DEFAULT_PRIME_DURATION = 0.50
RETRACT_PRIME_INCREMENT = 0.01
MIN_RETRACT_PRIME = 0.00
MAX_RETRACT_PRIME = 2.00

# --- Speed Ratio ---
DEFAULT_SPEED_RATIO = 1.0
RATIO_INCREMENT = 0.5
MIN_RATIO = 0.5
MAX_RATIO = 20.0

# --- Direction ---
EXT_FORWARD = 0
EXT_REVERSE = 1
FEED_FORWARD = 0
FEED_REVERSE = 1

# --- GUI Theme (Impact-inspired) ---
BG_LIGHT = "#f0f0f0"
BG_WHITE = "#ffffff"
BG_DARK = "#1a1a1a"
BG_CARD = "#e8e8e8"
BG_BUTTON = "#2d2d2d"
BORDER_LIGHT = "#e0e0e0"
TEXT_DARK = "#1a1a1a"
TEXT_MID = "#555555"
TEXT_LIGHT = "#999999"
TEXT_WHITE = "#ffffff"
TEXT_DISABLED = "#636e72"
ACCENT_ORANGE = "#e17055"
ACCENT_ORANGE_DARK = "#d35400"
COLOR_RED = "#d63031"
COLOR_GREEN = "#00b894"
COLOR_YELLOW = "#fdcb6e"
COLOR_GRAY = "#636e72"
STATUS_PILL_RED = "#d63031"
STATUS_PILL_GREEN = "#00b894"
STATUS_PILL_YELLOW = "#fdcb6e"
STATUS_PILL_GRAY = "#636e72"


# ============================================================
# STEPPER CONTROLLER
# ============================================================

class StepperController:
    def __init__(self, gpio_handle, step_pin, direction_pin, forward_val, reverse_val):
        self.h = gpio_handle
        self.step_pin = step_pin
        self.direction_pin = direction_pin
        self.forward_val = forward_val
        self.reverse_val = reverse_val

        lgpio.gpio_claim_output(self.h, self.step_pin)
        lgpio.gpio_claim_output(self.h, self.direction_pin)
        lgpio.gpio_write(self.h, self.direction_pin, self.forward_val)
        lgpio.gpio_write(self.h, self.step_pin, 0)
        self.running = False

    def set_forward(self):
        lgpio.gpio_write(self.h, self.direction_pin, self.forward_val)

    def set_reverse(self):
        lgpio.gpio_write(self.h, self.direction_pin, self.reverse_val)

    def start_stepping(self, steps_per_rev, speed_factor):
        steps_per_second = steps_per_rev * speed_factor
        if steps_per_second < 1:
            steps_per_second = 1
        lgpio.tx_pwm(self.h, self.step_pin, int(steps_per_second), 50)
        self.running = True

    def stop_stepping(self):
        lgpio.tx_pwm(self.h, self.step_pin, 0, 0)
        lgpio.gpio_write(self.h, self.step_pin, 0)
        self.running = False


# ============================================================
# EXTRUDER CONTROLLER
# ============================================================

class ExtruderController:
    STOPPED = "STOPPED"
    PRIMING = "PRIMING"
    EXTRUDING = "EXTRUDING"
    RETRACTING = "RETRACTING"

    def __init__(self, stepper, gpio_handle):
        self.stepper = stepper
        self.h = gpio_handle
        self.state = self.STOPPED
        self.speed_factor = DEFAULT_EXT_SPEED
        self.retract_duration = DEFAULT_RETRACT_DURATION
        self.prime_duration = DEFAULT_PRIME_DURATION
        self.manual_override = False
        self.manual_running = False
        self.override_stop = False
        self.run_start_time = None
        self.total_run_time = 0.0
        self.omnicore_signal = 0
        self.running = True
        self.lock = threading.Lock()
        self.on_state_change = None

        lgpio.gpio_claim_input(self.h, EXT_SIGNAL_PIN, lgpio.SET_PULL_DOWN)

    def get_rpm(self):
        return self.speed_factor * 60.0

    def get_run_time(self):
        if self.state == self.EXTRUDING and self.run_start_time:
            return self.total_run_time + (time.time() - self.run_start_time)
        return self.total_run_time

    def set_speed(self, speed_factor):
        with self.lock:
            self.speed_factor = round(
                max(MIN_SPEED_FACTOR, min(MAX_SPEED_FACTOR, speed_factor)), 2)
            if self.state == self.EXTRUDING:
                self.stepper.start_stepping(EXT_STEPS_PER_OUTPUT_REV, self.speed_factor)

    def set_retract_duration(self, duration):
        with self.lock:
            self.retract_duration = round(
                max(MIN_RETRACT_PRIME, min(MAX_RETRACT_PRIME, duration)), 2)

    def set_prime_duration(self, duration):
        with self.lock:
            self.prime_duration = round(
                max(MIN_RETRACT_PRIME, min(MAX_RETRACT_PRIME, duration)), 2)

    def toggle_manual_override(self):
        with self.lock:
            self.manual_override = not self.manual_override
            if not self.manual_override:
                self.manual_running = False
                self.override_stop = False

    def manual_start_stop(self):
        with self.lock:
            if self.manual_override:
                self.manual_running = not self.manual_running

    def toggle_override_stop(self):
        with self.lock:
            self.override_stop = not self.override_stop

    def _transition(self, new_state):
        self.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state)

    def _do_retract(self):
        if self.retract_duration <= 0:
            return
        self._transition(self.RETRACTING)
        self.stepper.set_reverse()
        self.stepper.start_stepping(EXT_STEPS_PER_OUTPUT_REV, self.speed_factor)
        time.sleep(self.retract_duration)
        self.stepper.stop_stepping()
        self.stepper.set_forward()

    def _do_prime(self):
        if self.prime_duration <= 0:
            return
        self._transition(self.PRIMING)
        self.stepper.set_forward()
        self.stepper.start_stepping(EXT_STEPS_PER_OUTPUT_REV, self.speed_factor)
        time.sleep(self.prime_duration)

    def control_loop(self):
        was_extruding = False
        while self.running:
            with self.lock:
                self.omnicore_signal = lgpio.gpio_read(self.h, EXT_SIGNAL_PIN)
                manual_override = self.manual_override
                manual_running = self.manual_running
                override_stop = self.override_stop

            if manual_override:
                should_run = manual_running
            else:
                should_run = (self.omnicore_signal == 1) and not override_stop

            if should_run and not was_extruding:
                self._do_prime()
                self._transition(self.EXTRUDING)
                self.stepper.set_forward()
                self.stepper.start_stepping(EXT_STEPS_PER_OUTPUT_REV, self.speed_factor)
                self.run_start_time = time.time()
                was_extruding = True
            elif not should_run and was_extruding:
                self.stepper.stop_stepping()
                if self.run_start_time:
                    self.total_run_time += time.time() - self.run_start_time
                    self.run_start_time = None
                self._do_retract()
                self._transition(self.STOPPED)
                was_extruding = False

            time.sleep(0.01)
        self.stepper.stop_stepping()

    def stop(self):
        self.running = False


# ============================================================
# FEEDER CONTROLLER
# ============================================================

class FeederController:
    IDLE = "IDLE"
    PI_CONTROL = "PI CTRL"
    FEEDING = "FEEDING"

    def __init__(self, stepper, gpio_handle, ext_controller=None):
        self.stepper = stepper
        self.h = gpio_handle
        self.ext = ext_controller
        self.state = self.IDLE
        self.speed_factor = DEFAULT_FEED_SPEED
        self.pi_has_control = False
        self.feeding = False
        self.linked = False
        self.ratio_locked = False
        self.speed_ratio = DEFAULT_SPEED_RATIO
        self.baseline_feed_speed = DEFAULT_FEED_SPEED
        self.baseline_ext_speed = DEFAULT_EXT_SPEED
        self.running = True
        self.lock = threading.Lock()
        self.on_state_change = None

        lgpio.gpio_claim_output(self.h, FEED_RELAY_PIN)
        lgpio.gpio_write(self.h, FEED_RELAY_PIN, 0)

    def set_speed(self, speed_factor):
        with self.lock:
            self.speed_factor = round(
                max(MIN_SPEED_FACTOR, min(MAX_SPEED_FACTOR, speed_factor)), 2)
            if self.state == self.FEEDING:
                self.stepper.start_stepping(FEED_STEPS_PER_OUTPUT_REV, self.speed_factor)

    def update_from_ratio(self, ext_speed):
        """Baseline + delta approach: feeder tracks extruder changes, not absolute value.
        delta = (current_ext - baseline_ext) * ratio
        new_feed = baseline_feed + delta
        """
        if self.ratio_locked:
            ext_delta = ext_speed - self.baseline_ext_speed
            feed_delta = ext_delta * self.speed_ratio
            new_speed = round(self.baseline_feed_speed + feed_delta, 2)
            new_speed = max(MIN_SPEED_FACTOR, min(MAX_SPEED_FACTOR, new_speed))
            self.speed_factor = new_speed
            if self.state == self.FEEDING:
                self.stepper.start_stepping(FEED_STEPS_PER_OUTPUT_REV, self.speed_factor)

    def toggle_ratio_lock(self):
        with self.lock:
            self.ratio_locked = not self.ratio_locked
            if self.ratio_locked and self.ext:
                # Capture current speeds as baselines
                self.baseline_feed_speed = self.speed_factor
                self.baseline_ext_speed = self.ext.speed_factor

    def set_speed_ratio(self, ratio):
        with self.lock:
            self.speed_ratio = round(
                max(MIN_RATIO, min(MAX_RATIO, ratio)), 1)
            if self.ratio_locked and self.ext:
                self.update_from_ratio(self.ext.speed_factor)

    def take_control(self):
        with self.lock:
            lgpio.gpio_write(self.h, FEED_RELAY_PIN, 1)
            self.pi_has_control = True
            self._transition(self.PI_CONTROL)

    def release_control(self):
        with self.lock:
            if self.feeding:
                self.stepper.stop_stepping()
                self.feeding = False
            lgpio.gpio_write(self.h, FEED_RELAY_PIN, 0)
            self.pi_has_control = False
            self._transition(self.IDLE)

    def toggle_control(self):
        if self.pi_has_control:
            self.release_control()
        else:
            self.take_control()

    def start_feeding(self):
        with self.lock:
            if not self.pi_has_control:
                return
            self.stepper.set_forward()
            self.stepper.start_stepping(FEED_STEPS_PER_OUTPUT_REV, self.speed_factor)
            self.feeding = True
            self._transition(self.FEEDING)

    def stop_feeding(self):
        with self.lock:
            self.stepper.stop_stepping()
            self.feeding = False
            if self.pi_has_control:
                self._transition(self.PI_CONTROL)
            else:
                self._transition(self.IDLE)

    def toggle_feeding(self):
        if self.feeding:
            self.stop_feeding()
        else:
            self.start_feeding()

    def toggle_linked(self):
        with self.lock:
            self.linked = not self.linked
            if self.linked and not self.pi_has_control:
                lgpio.gpio_write(self.h, FEED_RELAY_PIN, 1)
                self.pi_has_control = True
                self._transition(self.PI_CONTROL)

    def _transition(self, new_state):
        self.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state)

    def control_loop(self):
        was_extruding = False
        while self.running:
            with self.lock:
                linked = self.linked
                pi_has_control = self.pi_has_control

            if linked and pi_has_control and self.ext:
                ext_is_extruding = (self.ext.state == ExtruderController.EXTRUDING)

                if ext_is_extruding and not was_extruding:
                    self.start_feeding()
                    was_extruding = True
                elif not ext_is_extruding and was_extruding:
                    self.stop_feeding()
                    was_extruding = False
            elif not linked:
                was_extruding = False

            time.sleep(0.02)
        self.cleanup()

    def cleanup(self):
        self.stepper.stop_stepping()
        lgpio.gpio_write(self.h, FEED_RELAY_PIN, 0)

    def stop(self):
        self.running = False
        self.cleanup()


# ============================================================
# GUI - IMPACT-INSPIRED DESIGN
# ============================================================

class WaspControlGUI:
    def __init__(self, ext_controller, feed_controller):
        self.ext = ext_controller
        self.feed = feed_controller
        self.root = tk.Tk()
        self.root.title("WASP Control")
        self.root.configure(bg=BG_LIGHT)
        self.root.geometry("800x480")

        self.fullscreen = False
        self.root.bind("<Escape>", self.toggle_fullscreen)
        self.root.bind("<F11>", self.toggle_fullscreen)

        self.ext.on_state_change = self.on_ext_state_change
        self.feed.on_state_change = self.on_feed_state_change

        self.build_gui()
        self._fix_button_focus()
        self.update_display()

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def _fix_button_focus(self):
        """Touchscreen fix: makes activebackground/activeforeground match
        the button's normal bg/fg so there's no visible change on touch.
        Also re-syncs colors periodically to catch dynamically updated buttons."""
        self._sync_button_active_colors()

        def on_click(event):
            # Re-sync after click in case button colors changed
            self.root.after(50, self._sync_button_active_colors)
            self.root.after(50, lambda: self.root.focus_set())

        self.root.bind_all("<Button-1>", on_click)

    def _sync_button_active_colors(self):
        """Set activebackground=bg and activeforeground=fg on all buttons."""
        for btn in self._get_all_buttons(self.root):
            try:
                btn.configure(
                    activebackground=btn.cget("bg"),
                    activeforeground=btn.cget("fg"),
                    takefocus=False
                )
            except Exception:
                pass

    def _get_all_buttons(self, parent):
        """Recursively find all Button widgets."""
        buttons = []
        for child in parent.winfo_children():
            if isinstance(child, tk.Button):
                buttons.append(child)
            buttons.extend(self._get_all_buttons(child))
        return buttons

    def build_gui(self):
        # ============ TOP BAR ============
        top_bar = tk.Frame(self.root, bg=BG_DARK, height=44)
        top_bar.pack(fill=tk.X)
        top_bar.pack_propagate(False)

        title_frame = tk.Frame(top_bar, bg=BG_DARK)
        title_frame.pack(side=tk.LEFT, padx=15, pady=8)

        tk.Label(
            title_frame, text="WASP Control.", font=("Helvetica", 18, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK
        ).pack(side=tk.LEFT)

        accent_line = tk.Frame(title_frame, bg=ACCENT_ORANGE, width=30, height=3)
        accent_line.pack(side=tk.LEFT, padx=(5, 0), pady=(12, 0))

        # OmniCore signal
        signal_frame = tk.Frame(top_bar, bg=BG_BUTTON, padx=8, pady=2)
        signal_frame.pack(side=tk.RIGHT, padx=15, pady=8)

        self.signal_dot = tk.Label(
            signal_frame, text="●", font=("Helvetica", 10),
            fg=COLOR_RED, bg=BG_BUTTON
        )
        self.signal_dot.pack(side=tk.LEFT, padx=(0, 4))

        self.signal_label = tk.Label(
            signal_frame, text="OmniCore: LOW", font=("Helvetica", 10, "bold"),
            fg=TEXT_WHITE, bg=BG_BUTTON
        )
        self.signal_label.pack(side=tk.LEFT)

        # ============ MAIN CONTENT ============
        content = tk.Frame(self.root, bg=BG_LIGHT)
        content.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(content, bg=BG_LIGHT)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        divider = tk.Frame(content, bg=BG_DARK, width=2)
        divider.pack(side=tk.LEFT, fill=tk.Y)

        right = tk.Frame(content, bg=BG_LIGHT)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_extruder_panel(left)
        self._build_feeder_panel(right)

        # ============ ORANGE ACCENT LINE ============
        tk.Frame(self.root, bg=ACCENT_ORANGE, height=4).pack(fill=tk.X)

        # ============ BOTTOM BUTTON BAR ============
        btn_bar = tk.Frame(self.root, bg=BG_DARK, height=80)
        btn_bar.pack(fill=tk.X)
        btn_bar.pack_propagate(False)

        self._build_button_bar(btn_bar)

        # ============ FOOTER ============
        footer = tk.Frame(self.root, bg=BG_CARD, height=22)
        footer.pack(fill=tk.X)
        footer.pack_propagate(False)

        tk.Label(
            footer,
            text="CraftLab  ·  ABB GoFa CRB15000-10  ·  OmniCore  ·  University of Houston",
            font=("Helvetica", 7), fg=TEXT_LIGHT, bg=BG_CARD
        ).pack(side=tk.LEFT, padx=15, pady=3)

    # ---- Extruder Panel ----

    def _build_extruder_panel(self, parent):
        # Header
        header = tk.Frame(parent, bg=BG_DARK, height=32)
        header.pack(fill=tk.X, padx=(8, 4), pady=(6, 0))
        header.pack_propagate(False)

        tk.Label(
            header, text="EXTRUDER", font=("Helvetica", 12, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK
        ).pack(side=tk.LEFT, padx=10)

        self.ext_status_frame = tk.Frame(header, bg=STATUS_PILL_RED, padx=10, pady=1)
        self.ext_status_frame.pack(side=tk.RIGHT, padx=10, pady=4)
        self.ext_status_label = tk.Label(
            self.ext_status_frame, text="STOPPED", font=("Helvetica", 8, "bold"),
            fg=TEXT_WHITE, bg=STATUS_PILL_RED
        )
        self.ext_status_label.pack()

        # Info strip
        info = tk.Frame(parent, bg=BG_CARD, height=22)
        info.pack(fill=tk.X, padx=(8, 4), pady=(1, 0))
        info.pack_propagate(False)

        self.ext_rpm = tk.Label(
            info, text=f"RPM: {DEFAULT_EXT_SPEED * 60:.1f}",
            font=("Helvetica", 8, "bold"), fg=TEXT_MID, bg=BG_CARD
        )
        self.ext_rpm.pack(side=tk.LEFT, padx=10, pady=2)

        self.ext_runtime = tk.Label(
            info, text="Run: 0:00", font=("Helvetica", 8, "bold"),
            fg=TEXT_MID, bg=BG_CARD
        )
        self.ext_runtime.pack(side=tk.LEFT, padx=10)

        # Speed card
        speed_card = tk.Frame(parent, bg=BG_WHITE, highlightbackground=BORDER_LIGHT,
                              highlightthickness=1)
        speed_card.pack(fill=tk.X, padx=(8, 4), pady=(2, 0))

        speed_inner = tk.Frame(speed_card, bg=BG_WHITE, pady=6, padx=8)
        speed_inner.pack(fill=tk.X)

        tk.Label(
            speed_inner, text="SPEED", font=("Helvetica", 8, "bold"),
            fg=TEXT_DARK, bg=BG_WHITE
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            speed_inner, text="−", font=("Helvetica", 16, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK, activebackground=BG_BUTTON,
            width=3, relief=tk.FLAT, bd=0,
            command=lambda: self._ext_speed_change(-SPEED_INCREMENT)
        ).pack(side=tk.LEFT, padx=4)

        self.ext_speed_display = tk.Label(
            speed_inner, text=f"{DEFAULT_EXT_SPEED:.2f}",
            font=("Helvetica", 24, "bold"), fg=TEXT_DARK, bg=BG_WHITE, width=5
        )
        self.ext_speed_display.pack(side=tk.LEFT, padx=8)

        tk.Button(
            speed_inner, text="+", font=("Helvetica", 16, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK, activebackground=BG_BUTTON,
            width=3, relief=tk.FLAT, bd=0,
            command=lambda: self._ext_speed_change(SPEED_INCREMENT)
        ).pack(side=tk.LEFT, padx=4)

        # Retract / Prime row
        rp_frame = tk.Frame(parent, bg=BG_LIGHT)
        rp_frame.pack(fill=tk.X, padx=(8, 4), pady=(2, 0))

        # Retract card
        ret_card = tk.Frame(rp_frame, bg=BG_WHITE, highlightbackground=BORDER_LIGHT,
                            highlightthickness=1)
        ret_card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 1))

        ret_inner = tk.Frame(ret_card, bg=BG_WHITE, pady=4, padx=6)
        ret_inner.pack(fill=tk.X)

        tk.Label(ret_inner, text="RETRACT (s)", font=("Helvetica", 7, "bold"),
                 fg=TEXT_DARK, bg=BG_WHITE).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(ret_inner, text="−", font=("Helvetica", 10, "bold"),
                  fg=TEXT_WHITE, bg=BG_DARK, width=2, relief=tk.FLAT,
                  command=lambda: self.ext.set_retract_duration(
                      self.ext.retract_duration - RETRACT_PRIME_INCREMENT)
                  ).pack(side=tk.LEFT, padx=2)

        self.ext_retract_display = tk.Label(
            ret_inner, text="0.50", font=("Helvetica", 13, "bold"),
            fg=TEXT_DARK, bg=BG_WHITE, width=4)
        self.ext_retract_display.pack(side=tk.LEFT, padx=3)

        tk.Button(ret_inner, text="+", font=("Helvetica", 10, "bold"),
                  fg=TEXT_WHITE, bg=BG_DARK, width=2, relief=tk.FLAT,
                  command=lambda: self.ext.set_retract_duration(
                      self.ext.retract_duration + RETRACT_PRIME_INCREMENT)
                  ).pack(side=tk.LEFT, padx=2)

        # Prime card
        pri_card = tk.Frame(rp_frame, bg=BG_WHITE, highlightbackground=BORDER_LIGHT,
                            highlightthickness=1)
        pri_card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(1, 0))

        pri_inner = tk.Frame(pri_card, bg=BG_WHITE, pady=4, padx=6)
        pri_inner.pack(fill=tk.X)

        tk.Label(pri_inner, text="PRIME (s)", font=("Helvetica", 7, "bold"),
                 fg=TEXT_DARK, bg=BG_WHITE).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(pri_inner, text="−", font=("Helvetica", 10, "bold"),
                  fg=TEXT_WHITE, bg=BG_DARK, width=2, relief=tk.FLAT,
                  command=lambda: self.ext.set_prime_duration(
                      self.ext.prime_duration - RETRACT_PRIME_INCREMENT)
                  ).pack(side=tk.LEFT, padx=2)

        self.ext_prime_display = tk.Label(
            pri_inner, text="0.50", font=("Helvetica", 13, "bold"),
            fg=TEXT_DARK, bg=BG_WHITE, width=4)
        self.ext_prime_display.pack(side=tk.LEFT, padx=3)

        tk.Button(pri_inner, text="+", font=("Helvetica", 10, "bold"),
                  fg=TEXT_WHITE, bg=BG_DARK, width=2, relief=tk.FLAT,
                  command=lambda: self.ext.set_prime_duration(
                      self.ext.prime_duration + RETRACT_PRIME_INCREMENT)
                  ).pack(side=tk.LEFT, padx=2)

        # Reset timer
        tk.Button(
            parent, text="RESET TIMER", font=("Helvetica", 7, "bold"),
            fg=TEXT_MID, bg=BG_CARD, activebackground=BORDER_LIGHT,
            relief=tk.FLAT, bd=0, padx=8, pady=2,
            command=self.reset_runtime
        ).pack(anchor=tk.W, padx=(8, 4), pady=(3, 0))

    # ---- Feeder Panel ----

    def _build_feeder_panel(self, parent):
        # Header
        header = tk.Frame(parent, bg=BG_DARK, height=32)
        header.pack(fill=tk.X, padx=(4, 8), pady=(6, 0))
        header.pack_propagate(False)

        tk.Label(
            header, text="FEEDER", font=("Helvetica", 12, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK
        ).pack(side=tk.LEFT, padx=10)

        self.feed_status_frame = tk.Frame(header, bg=STATUS_PILL_GRAY, padx=10, pady=1)
        self.feed_status_frame.pack(side=tk.RIGHT, padx=10, pady=4)
        self.feed_status_label = tk.Label(
            self.feed_status_frame, text="IDLE", font=("Helvetica", 8, "bold"),
            fg=TEXT_WHITE, bg=STATUS_PILL_GRAY
        )
        self.feed_status_label.pack()

        # Control status strip
        ctrl_strip = tk.Frame(parent, bg=BG_CARD, height=22)
        ctrl_strip.pack(fill=tk.X, padx=(4, 8), pady=(1, 0))
        ctrl_strip.pack_propagate(False)

        self.feed_control_label = tk.Label(
            ctrl_strip, text="Control: Front Panel",
            font=("Helvetica", 8, "bold"), fg=TEXT_MID, bg=BG_CARD
        )
        self.feed_control_label.pack(side=tk.LEFT, padx=10, pady=2)

        # Speed card
        speed_card = tk.Frame(parent, bg=BG_WHITE, highlightbackground=BORDER_LIGHT,
                              highlightthickness=1)
        speed_card.pack(fill=tk.X, padx=(4, 8), pady=(2, 0))

        speed_inner = tk.Frame(speed_card, bg=BG_WHITE, pady=6, padx=8)
        speed_inner.pack(fill=tk.X)

        tk.Label(
            speed_inner, text="SPEED", font=("Helvetica", 8, "bold"),
            fg=TEXT_DARK, bg=BG_WHITE
        ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(
            speed_inner, text="−", font=("Helvetica", 16, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK, activebackground=BG_BUTTON,
            width=3, relief=tk.FLAT, bd=0,
            command=lambda: self.feed.set_speed(self.feed.speed_factor - SPEED_INCREMENT)
        ).pack(side=tk.LEFT, padx=4)

        self.feed_speed_display = tk.Label(
            speed_inner, text=f"{DEFAULT_FEED_SPEED:.2f}",
            font=("Helvetica", 24, "bold"), fg=TEXT_DARK, bg=BG_WHITE, width=5
        )
        self.feed_speed_display.pack(side=tk.LEFT, padx=8)

        tk.Button(
            speed_inner, text="+", font=("Helvetica", 16, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK, activebackground=BG_BUTTON,
            width=3, relief=tk.FLAT, bd=0,
            command=lambda: self.feed.set_speed(self.feed.speed_factor + SPEED_INCREMENT)
        ).pack(side=tk.LEFT, padx=4)

        # Speed Ratio row (matches Retract/Prime style)
        ratio_card = tk.Frame(parent, bg=BG_WHITE, highlightbackground=BORDER_LIGHT,
                              highlightthickness=1)
        ratio_card.pack(fill=tk.X, padx=(4, 8), pady=(2, 0))

        ratio_inner = tk.Frame(ratio_card, bg=BG_WHITE, pady=4, padx=6)
        ratio_inner.pack(fill=tk.X)

        tk.Label(ratio_inner, text="SPEED RATIO", font=("Helvetica", 7, "bold"),
                 fg=TEXT_DARK, bg=BG_WHITE).pack(side=tk.LEFT, padx=(0, 4))

        tk.Button(ratio_inner, text="−", font=("Helvetica", 10, "bold"),
                  fg=TEXT_WHITE, bg=BG_DARK, width=2, relief=tk.FLAT,
                  command=lambda: self.feed.set_speed_ratio(
                      self.feed.speed_ratio - RATIO_INCREMENT)
                  ).pack(side=tk.LEFT, padx=2)

        self.ratio_label = tk.Label(
            ratio_inner, text=f"{DEFAULT_SPEED_RATIO:.1f}x",
            font=("Helvetica", 13, "bold"),
            fg=TEXT_DARK, bg=BG_WHITE, width=5)
        self.ratio_label.pack(side=tk.LEFT, padx=3)

        tk.Button(ratio_inner, text="+", font=("Helvetica", 10, "bold"),
                  fg=TEXT_WHITE, bg=BG_DARK, width=2, relief=tk.FLAT,
                  command=lambda: self.feed.set_speed_ratio(
                      self.feed.speed_ratio + RATIO_INCREMENT)
                  ).pack(side=tk.LEFT, padx=2)

        # LINK TO EXTRUDER + RATIO LOCK -- side by side, large buttons
        link_ratio_frame = tk.Frame(parent, bg=BG_LIGHT)
        link_ratio_frame.pack(fill=tk.X, padx=(4, 8), pady=(2, 0))

        self.link_btn = tk.Button(
            link_ratio_frame, text="LINK TO\nEXTRUDER",
            font=("Helvetica", 9, "bold"),
            fg=TEXT_WHITE, bg=BG_DARK,
            activebackground=BG_BUTTON,
            relief=tk.FLAT, bd=0, pady=6,
            command=self.feed_toggle_linked
        )
        self.link_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        self.ratio_btn = tk.Button(
            link_ratio_frame, text="RATIO\nLOCK OFF",
            font=("Helvetica", 9, "bold"),
            fg=TEXT_MID, bg=BG_CARD,
            activebackground=BORDER_LIGHT,
            relief=tk.FLAT, bd=0, pady=6,
            command=self.toggle_ratio_lock
        )
        self.ratio_btn.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0))

        # Linked status
        self.linked_status = tk.Label(
            parent, text="", font=("Helvetica", 8, "bold"),
            fg=TEXT_LIGHT, bg=BG_LIGHT
        )
        self.linked_status.pack(fill=tk.X, padx=(4, 8), pady=(1, 0))

    # ---- Bottom Button Bar ----

    def _build_button_bar(self, parent):
        inner = tk.Frame(parent, bg=BG_DARK, pady=8, padx=8)
        inner.pack(fill=tk.BOTH, expand=True)

        # --- Extruder buttons (left half) ---
        ext_btns = tk.Frame(inner, bg=BG_DARK)
        ext_btns.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.ext_manual_btn = tk.Button(
            ext_btns, text="MANUAL\nOVERRIDE", font=("Helvetica", 9, "bold"),
            fg=TEXT_WHITE, bg=BG_BUTTON,
            activebackground=COLOR_GRAY,
            width=10, relief=tk.FLAT, bd=0,
            command=self.ext_toggle_manual
        )
        self.ext_manual_btn.pack(side=tk.LEFT, padx=(0, 4), fill=tk.Y)

        self.ext_start_btn = tk.Button(
            ext_btns, text="START", font=("Helvetica", 13, "bold"),
            fg=TEXT_DISABLED, bg=BG_BUTTON,
            activebackground=COLOR_GRAY,
            width=9, relief=tk.FLAT, bd=0,
            command=self.ext_start_stop, state=tk.DISABLED
        )
        self.ext_start_btn.pack(side=tk.LEFT, padx=4, fill=tk.Y)

        self.ext_stop_btn = tk.Button(
            ext_btns, text="STOP", font=("Helvetica", 12, "bold"),
            fg=TEXT_WHITE, bg=COLOR_RED,
            activebackground="#c0392b",
            width=9, relief=tk.FLAT, bd=0,
            command=self.ext_stop_action
        )
        self.ext_stop_btn.pack(side=tk.LEFT, padx=4, fill=tk.Y)

        # --- Feeder buttons (right half) ---
        feed_btns = tk.Frame(inner, bg=BG_DARK)
        feed_btns.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        self.feed_stop_btn = tk.Button(
            feed_btns, text="STOP\nFEED", font=("Helvetica", 9, "bold"),
            fg=TEXT_WHITE, bg=COLOR_RED,
            activebackground="#c0392b",
            width=9, relief=tk.FLAT, bd=0,
            command=self.feed_stop
        )
        self.feed_stop_btn.pack(side=tk.RIGHT, padx=(4, 0), fill=tk.Y)

        self.feed_start_btn = tk.Button(
            feed_btns, text="START\nFEED", font=("Helvetica", 9, "bold"),
            fg=TEXT_DISABLED, bg=BG_BUTTON,
            activebackground=COLOR_GRAY,
            width=9, relief=tk.FLAT, bd=0,
            command=self.feed_toggle, state=tk.DISABLED
        )
        self.feed_start_btn.pack(side=tk.RIGHT, padx=4, fill=tk.Y)

        self.feed_control_btn = tk.Button(
            feed_btns, text="TAKE\nCONTROL", font=("Helvetica", 9, "bold"),
            fg=TEXT_WHITE, bg=ACCENT_ORANGE,
            activebackground=ACCENT_ORANGE_DARK,
            width=10, relief=tk.FLAT, bd=0,
            command=self.feed_toggle_control
        )
        self.feed_control_btn.pack(side=tk.RIGHT, padx=4, fill=tk.Y)

    # ============================================================
    # ACTIONS
    # ============================================================

    def _ext_speed_change(self, delta):
        self.ext.set_speed(self.ext.speed_factor + delta)
        if self.feed.ratio_locked:
            self.feed.update_from_ratio(self.ext.speed_factor)

    def reset_runtime(self):
        self.ext.total_run_time = 0.0
        self.ext.run_start_time = (
            time.time() if self.ext.state == ExtruderController.EXTRUDING else None
        )

    # -- Extruder --

    def ext_toggle_manual(self):
        self.ext.toggle_manual_override()
        if self.ext.manual_override:
            self.ext_manual_btn.configure(bg=COLOR_YELLOW, fg=TEXT_DARK,
                                          activebackground=COLOR_YELLOW)
            self.ext_start_btn.configure(state=tk.NORMAL, fg=TEXT_WHITE)
        else:
            self.ext_manual_btn.configure(bg=BG_BUTTON, fg=TEXT_WHITE,
                                          activebackground=COLOR_GRAY)
            self.ext_start_btn.configure(state=tk.DISABLED, fg=TEXT_DISABLED,
                                         text="START")

    def ext_start_stop(self):
        self.ext.manual_start_stop()
        if self.ext.manual_running:
            self.ext_start_btn.configure(text="RUNNING", bg=COLOR_GREEN, fg=TEXT_WHITE,
                                         activebackground=COLOR_GREEN)
        else:
            self.ext_start_btn.configure(text="START", bg=BG_BUTTON, fg=TEXT_WHITE,
                                         activebackground=COLOR_GRAY)

    def ext_stop_action(self):
        if self.ext.manual_override and self.ext.manual_running:
            self.ext.manual_start_stop()
            self.ext_start_btn.configure(text="START", bg=BG_BUTTON, fg=TEXT_WHITE,
                                         activebackground=COLOR_GRAY)
        else:
            self.ext.toggle_override_stop()

    # -- Feeder --

    def feed_toggle_control(self):
        self.feed.toggle_control()
        if self.feed.pi_has_control:
            self.feed_control_btn.configure(text="RELEASE\nCONTROL",
                                            bg=COLOR_YELLOW, fg=TEXT_DARK,
                                            activebackground=COLOR_YELLOW)
            self.feed_start_btn.configure(state=tk.NORMAL, fg=TEXT_WHITE)
        else:
            self.feed_control_btn.configure(text="TAKE\nCONTROL",
                                            bg=ACCENT_ORANGE, fg=TEXT_WHITE,
                                            activebackground=ACCENT_ORANGE_DARK)
            self.feed_start_btn.configure(state=tk.DISABLED, fg=TEXT_DISABLED,
                                          text="START\nFEED")

    def feed_toggle(self):
        self.feed.toggle_feeding()
        if self.feed.feeding:
            self.feed_start_btn.configure(text="FEEDING", bg=COLOR_GREEN, fg=TEXT_WHITE,
                                          activebackground=COLOR_GREEN)
        else:
            self.feed_start_btn.configure(text="START\nFEED", bg=BG_BUTTON, fg=TEXT_WHITE,
                                          activebackground=COLOR_GRAY)

    def feed_stop(self):
        self.feed.stop_feeding()
        self.feed_start_btn.configure(text="START\nFEED", bg=BG_BUTTON, fg=TEXT_WHITE,
                                      activebackground=COLOR_GRAY)

    def feed_toggle_linked(self):
        self.feed.toggle_linked()
        if self.feed.linked:
            self.link_btn.configure(bg=COLOR_GREEN, fg=TEXT_WHITE, text="LINKED\n✓",
                                    activebackground=COLOR_GREEN)
            if not self.feed.pi_has_control:
                self.feed_toggle_control()
        else:
            self.link_btn.configure(bg=BG_DARK, fg=TEXT_WHITE, text="LINK TO\nEXTRUDER",
                                    activebackground=BG_BUTTON)

    def toggle_ratio_lock(self):
        self.feed.toggle_ratio_lock()
        if self.feed.ratio_locked:
            self.ratio_btn.configure(text="RATIO\nLOCK ON", bg=COLOR_GREEN, fg=TEXT_WHITE,
                                     activebackground=COLOR_GREEN)
        else:
            self.ratio_btn.configure(text="RATIO\nLOCK OFF", bg=BG_CARD, fg=TEXT_MID,
                                     activebackground=BORDER_LIGHT)

    # ============================================================
    # STATE CALLBACKS
    # ============================================================

    def on_ext_state_change(self, state):
        self.root.after(0, self._update_ext_status, state)

    def on_feed_state_change(self, state):
        self.root.after(0, self._update_feed_status, state)

    def _update_ext_status(self, state):
        config = {
            ExtruderController.STOPPED:    ("STOPPED",    STATUS_PILL_RED),
            ExtruderController.PRIMING:    ("PRIMING",    STATUS_PILL_YELLOW),
            ExtruderController.EXTRUDING:  ("EXTRUDING",  STATUS_PILL_GREEN),
            ExtruderController.RETRACTING: ("RETRACTING", STATUS_PILL_YELLOW),
        }
        text, color = config.get(state, ("UNKNOWN", STATUS_PILL_GRAY))
        self.ext_status_label.configure(text=text, bg=color)
        self.ext_status_frame.configure(bg=color)

        # Context-sensitive stop button
        if not self.ext.manual_override and self.ext.omnicore_signal == 1:
            if self.ext.override_stop:
                self.ext_stop_btn.configure(text="OVERRIDE\nACTIVE",
                                            bg=COLOR_YELLOW, fg=TEXT_DARK,
                                            activebackground=COLOR_YELLOW)
            else:
                self.ext_stop_btn.configure(text="OVERRIDE\nSTOP",
                                            bg=COLOR_RED, fg=TEXT_WHITE,
                                            activebackground=COLOR_RED)
        else:
            if self.ext.override_stop:
                self.ext.override_stop = False
            self.ext_stop_btn.configure(text="STOP", bg=COLOR_RED, fg=TEXT_WHITE,
                                        activebackground=COLOR_RED)

    def _update_feed_status(self, state):
        config = {
            FeederController.IDLE:       ("IDLE",    STATUS_PILL_GRAY),
            FeederController.PI_CONTROL: ("PI CTRL", STATUS_PILL_YELLOW),
            FeederController.FEEDING:    ("FEEDING", STATUS_PILL_GREEN),
        }
        text, color = config.get(state, ("UNKNOWN", STATUS_PILL_GRAY))
        self.feed_status_label.configure(text=text, bg=color)
        self.feed_status_frame.configure(bg=color)

    # ============================================================
    # PERIODIC DISPLAY UPDATE
    # ============================================================

    def update_display(self):
        # Extruder
        self.ext_speed_display.configure(text=f"{self.ext.speed_factor:.2f}")
        self.ext_retract_display.configure(text=f"{self.ext.retract_duration:.2f}")
        self.ext_prime_display.configure(text=f"{self.ext.prime_duration:.2f}")
        self.ext_rpm.configure(text=f"RPM: {self.ext.get_rpm():.1f}")

        run_time = self.ext.get_run_time()
        minutes = int(run_time // 60)
        seconds = int(run_time % 60)
        self.ext_runtime.configure(text=f"Run: {minutes}:{seconds:02d}")

        # OmniCore signal
        if self.ext.omnicore_signal:
            self.signal_dot.configure(fg=COLOR_GREEN)
            self.signal_label.configure(text="OmniCore: HIGH")
        else:
            self.signal_dot.configure(fg=COLOR_RED)
            self.signal_label.configure(text="OmniCore: LOW")

        self._update_ext_status(self.ext.state)

        # Feeder
        self.feed_speed_display.configure(text=f"{self.feed.speed_factor:.2f}")

        if self.feed.pi_has_control:
            self.feed_control_label.configure(text="Control: Raspberry Pi",
                                              fg=COLOR_GREEN)
        else:
            self.feed_control_label.configure(text="Control: Front Panel",
                                              fg=TEXT_MID)

        # Ratio
        self.ratio_label.configure(text=f"{self.feed.speed_ratio:.1f}x")

        # Linked status
        if self.feed.linked:
            if self.feed.feeding:
                self.linked_status.configure(
                    text="⚡ LINKED — Feeding with extruder", fg=COLOR_GREEN)
            else:
                self.linked_status.configure(
                    text="⚡ LINKED — Waiting for extruder", fg=COLOR_YELLOW)
        else:
            self.linked_status.configure(text="")

        self._update_feed_status(self.feed.state)

        # Keep active colors synced with current button colors
        self._sync_button_active_colors()

        self.root.after(100, self.update_display)

    def run(self):
        self.root.mainloop()


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 50)
    print("WASP Dual Controller")
    print("Extruder + Continuous Feeder")
    print("Raspberry Pi 5 + lgpio")
    print("University of Houston - CraftLab")
    print("=" * 50)

    h = lgpio.gpiochip_open(GPIO_CHIP)
    if h < 0:
        print(f"✗ Could not open GPIO chip {GPIO_CHIP}")
        return
    print(f"✓ GPIO chip {GPIO_CHIP} opened")

    ext_stepper = StepperController(
        h, EXT_STEP_PIN, EXT_DIRECTION_PIN, EXT_FORWARD, EXT_REVERSE
    )
    print(f"  Extruder: GPIO {EXT_STEP_PIN} (step), {EXT_DIRECTION_PIN} (dir)")

    feed_stepper = StepperController(
        h, FEED_STEP_PIN, FEED_DIRECTION_PIN, FEED_FORWARD, FEED_REVERSE
    )
    print(f"  Feeder:   GPIO {FEED_STEP_PIN} (step), {FEED_DIRECTION_PIN} (dir)")
    print(f"  Relay:    GPIO {FEED_RELAY_PIN}")

    ext_controller = ExtruderController(ext_stepper, h)
    feed_controller = FeederController(feed_stepper, h, ext_controller)
    print("✓ Controllers initialized")

    ext_thread = threading.Thread(target=ext_controller.control_loop, daemon=True)
    ext_thread.start()
    print("✓ Extruder control loop started")

    feed_thread = threading.Thread(target=feed_controller.control_loop, daemon=True)
    feed_thread.start()
    print("✓ Feeder control loop started")

    print("✓ Starting GUI...")
    print("-" * 50)

    gui = WaspControlGUI(ext_controller, feed_controller)

    try:
        gui.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        ext_controller.stop()
        feed_controller.stop()
        ext_thread.join(timeout=2)
        feed_thread.join(timeout=2)
        lgpio.gpiochip_close(h)
        print("✓ Cleanup complete")


if __name__ == "__main__":
    main()
