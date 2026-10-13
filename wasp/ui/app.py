"""
Main window: side rail (RUN / PROFILES / SETUP / STOP ALL) and three pages.

The GUI never blocks and never touches GPIO; it calls Machine methods and
redraws from Machine state every 100 ms. Switching theme destroys and
rebuilds every widget (state lives in Machine / ProfileStore, so nothing is lost).
"""

import threading
import time
import tkinter as tk

from .. import __version__
from .. import config as C
from ..motion import Extruder, Feeder, rpm_to_hz
from ..profiles import MAX_NAME_LEN, same_settings
from .. import updates as U
from .theme import THEMES, font, pick_family
from .widgets import Confirm, Keypad, Pill, TextForm, TouchButton, set_label, text_label

W, H = 800, 480
RAIL_W = 96
LIST_SLOTS = 5
POLL_MS = 100
NUDGE_W, NUDGE_H = 58, 84


class App:
    def __init__(self, machine, store, settings, fullscreen=False, update_checker=None):
        self.m = machine
        self.ext = machine.extruder
        self.feed = machine.feeder
        self.store = store
        self.settings = settings

        self.root = tk.Tk()
        self.root.title("WASP Control")
        self.root.geometry(f"{W}x{H}")
        pick_family(self.root)
        self.fullscreen = fullscreen
        self.root.attributes("-fullscreen", fullscreen)
        self.root.bind("<F11>", lambda _e: self.toggle_fullscreen())
        self.root.bind("<Escape>", lambda _e: self.toggle_fullscreen())
        self.root.report_callback_exception = self.on_error

        self.page = "profiles"
        self.current = None                  # name of the loaded profile
        self.selected = store.default_name   # highlighted on the Profiles page
        self.list_offset = 0
        self.frame = None
        self._toast_job = None
        self.update_checker = update_checker   # e.g. updates.check; None = off
        self.update_info = None                # last result from the checker
        self._update_announced = False

        self.build()
        self.root.after(POLL_MS, self.poll)
        if update_checker:
            self.root.after(3000, self._periodic_check)

    # ============================================================
    # BUILD
    # ============================================================

    @property
    def t(self):
        return THEMES.get(self.settings["theme"], THEMES["dark"])

    def build(self):
        if self.frame:
            self.frame.destroy()
        t = self.t
        self.root.configure(bg=t["bg"])
        self.frame = tk.Frame(self.root, bg=t["bg"])
        self.frame.pack(fill="both", expand=True)

        self._build_rail()
        self.main = tk.Frame(self.frame, bg=t["bg"])
        self.main.pack(side="left", fill="both", expand=True)

        self.pages = {}
        for name, builder in (("run", self._build_run), ("profiles", self._build_profiles),
                              ("setup", self._build_setup)):
            page = tk.Frame(self.main, bg=t["bg"])
            page.place(x=0, y=0, relwidth=1, relheight=1)
            builder(page)
            self.pages[name] = page

        self.toast = text_label(self.main, "", 14, t["accent_fg"], t["accent"], padx=16, pady=8)
        self.show(self.page)
        self.refresh_profiles()
        self.poll(schedule=False)

    def btn(self, parent, text, cmd, w, h, kind="raised", size=14, **kw):
        t = self.t
        bg, fg = {
            "raised": (t["raised"], t["raised_fg"]),
            "accent": (t["accent"], t["accent_fg"]),
            "red": (t["red"], t["red_fg"]),
            "green": (t["green"], t["green_fg"]),
            "yellow": (t["yellow"], t["yellow_fg"]),
        }[kind]
        return TouchButton(parent, text, cmd, w, h, bg, fg, size=size,
                           disabled_bg=t["disabled_bg"], disabled_fg=t["disabled_fg"], **kw)

    def card(self, parent, **pack):
        t = self.t
        f = tk.Frame(parent, bg=t["surface"], highlightthickness=1,
                     highlightbackground=t["border"], padx=10, pady=8)
        f.pack(**pack)
        return f

    def header(self, parent):
        t = self.t
        hdr = tk.Frame(parent, bg=t["surface"], height=46, highlightthickness=1,
                       highlightbackground=t["border"])
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        return hdr

    # ---- rail ----

    def _build_rail(self):
        t = self.t
        rail = tk.Frame(self.frame, bg=t["rail"], width=RAIL_W)
        rail.pack(side="left", fill="y")
        rail.pack_propagate(False)
        logo = tk.Frame(rail, bg=t["rail"])
        logo.pack(pady=(10, 8))
        text_label(logo, "WASP", 18, "#ffffff", t["rail"]).pack(side="left")
        text_label(logo, ".", 18, t["accent"], t["rail"]).pack(side="left")

        self.nav = {}
        for key, label in (("run", "▶\nRUN"), ("profiles", "☰\nPROFILES"), ("setup", "⚙\nSETUP")):
            b = TouchButton(rail, label, lambda k=key: self.show(k), 82, 68,
                            t["rail"], t["rail_fg"], size=13)
            b.pack(pady=3)
            self.nav[key] = b
        # Dot on SETUP when a newer version is on GitHub.
        self.update_badge = text_label(self.nav["setup"], "●", 16, t["green"], t["rail"])
        self.update_badge.bind("<ButtonPress-1>", self.nav["setup"]._press)
        self.update_badge.bind("<ButtonRelease-1>", self.nav["setup"]._release)

        TouchButton(rail, "STOP\nALL", self.stop_all, 82, 104, t["red"], "#ffffff",
                    size=17, fire_on_press=True).pack(side="bottom", pady=8)

    def show(self, page):
        self.page = page
        self.pages[page].tkraise()
        self.toast.lift()
        t = self.t
        for key, b in self.nav.items():
            on = key == page
            b.set(bg=t["rail_on"] if on else t["rail"], fg=t["rail_on_fg"] if on else t["rail_fg"])
        if page == "profiles":
            self.refresh_profiles()

    # ---- RUN page ----

    def _build_run(self, page):
        t = self.t
        hdr = self.header(page)
        text_label(hdr, "PROFILE", 10, t["muted"], t["surface"]).pack(side="left", padx=(12, 6))
        self.run_name = text_label(hdr, "", 16, t["text"], t["surface"])
        self.run_name.pack(side="left")
        self.run_modified = Pill(hdr, "", t["surface"], t["surface"], size=10)
        self.run_modified.pack(side="left", padx=8)
        self.btn(hdr, "SAVE", self.save_current, 64, 32, "accent", 12).pack(side="left", padx=(0, 6))
        self.btn(hdr, "SAVE AS…", self.save_as, 86, 32, "raised", 12).pack(side="left")
        self.omni_pill = Pill(hdr, "", t["raised"], t["raised_fg"], size=11)
        self.omni_pill.pack(side="right", padx=10)
        if self.m.simulated:
            Pill(hdr, "SIM", t["yellow"], t["yellow_fg"], size=10).pack(side="right")

        # Action bar first (packed to the bottom) so the bands take the rest.
        bar = tk.Frame(page, bg=t["bg"])
        bar.pack(side="bottom", fill="x", padx=8, pady=8)
        self.b_manual = self.btn(bar, "MANUAL", self.ext.toggle_manual_override, 96, 70, size=14)
        self.b_manual.pack(side="left")
        self.b_start = self.btn(bar, "START", self.ext.manual_start_stop, 96, 70, size=15)
        self.b_start.pack(side="left", padx=6)
        self.b_stop = self.btn(bar, "STOP", self.ext.stop_button, 128, 70, "red", 15,
                               fire_on_press=True)
        self.b_stop.pack(side="left")
        self.b_feedstop = self.btn(bar, "STOP\nFEED", self.feed.stop_feeding, 104, 70, "red", 14,
                                   fire_on_press=True)
        self.b_feedstop.pack(side="right")
        self.b_feedstart = self.btn(bar, "START\nFEED", self.feed_start_toggle, 100, 70, size=14)
        self.b_feedstart.pack(side="right", padx=6)
        self.b_control = self.btn(bar, "TAKE\nCONTROL", self.feeder_control_toggle, 112, 70,
                                  "green", 14)
        self.b_control.pack(side="right")

        self._build_ext_band(page)
        self._build_feed_band(page)

    def _band_top(self, band, title):
        t = self.t
        top = tk.Frame(band, bg=t["surface"])
        top.pack(fill="x")
        text_label(top, title, 15, t["text"], t["surface"]).pack(side="left")
        pill = Pill(top, "", t["gray"], t["gray_fg"], size=10)
        pill.pack(side="left", padx=8)
        right = text_label(top, "", 11, t["muted"], t["surface"], bold=False)
        right.pack(side="right")
        return top, pill, right

    def _value_box(self, parent, unit, on_tap, width=164):
        t = self.t
        box = tk.Frame(parent, bg=t["inset"], width=width, height=NUDGE_H)
        box.pack_propagate(False)
        inner = tk.Frame(box, bg=t["inset"])
        inner.place(relx=0.5, rely=0.5, anchor="center")
        val = text_label(inner, "", 46, t["text"], t["inset"])
        val.pack(side="left")
        u = text_label(inner, unit, 13, t["muted"], t["inset"])
        u.pack(side="left", anchor="s", pady=(0, 10), padx=(4, 0))
        for wdg in (box, inner, val, u):
            wdg.bind("<ButtonRelease-1>", lambda _e: on_tap())
        return box, val

    def _small_row(self, parent, caption, minus, plus, on_tap):
        t = self.t
        row = tk.Frame(parent, bg=t["surface"])
        row.pack(fill="x", pady=4)
        text_label(row, caption, 10, t["muted"], t["surface"], width=8, anchor="w").pack(side="left")
        self.btn(row, "−", minus, 44, 34, size=18, repeat=True).pack(side="left")
        val = text_label(row, "", 16, t["text"], t["surface"], width=6)
        val.pack(side="left", padx=2)
        val.bind("<ButtonRelease-1>", lambda _e: on_tap())
        self.btn(row, "+", plus, 44, 34, size=18, repeat=True).pack(side="left")
        return val

    def _build_ext_band(self, page):
        t = self.t
        band = self.card(page, fill="x", padx=8, pady=(8, 0))
        top, self.ext_pill, self.ext_detail = self._band_top(band, "EXTRUDER")
        self.ext_timer = text_label(top, "", 12, t["muted"], t["surface"])
        self.ext_timer.pack(side="left")

        row = tk.Frame(band, bg=t["surface"])
        row.pack(fill="x", pady=(6, 0))
        nudge = lambda d: (lambda: self.m.set_ext_rpm(self.ext.rpm + d))
        self.btn(row, "−1", nudge(-1), NUDGE_W, NUDGE_H, size=15, repeat=True).pack(side="left")
        self.btn(row, "−0.1", nudge(-0.1), NUDGE_W, NUDGE_H, size=14, repeat=True).pack(side="left", padx=4)
        box, self.ext_val = self._value_box(row, "RPM", self.keypad_ext)
        box.pack(side="left")
        self.btn(row, "+0.1", nudge(0.1), NUDGE_W, NUDGE_H, size=14, repeat=True).pack(side="left", padx=4)
        self.btn(row, "+1", nudge(1), NUDGE_W, NUDGE_H, size=15, repeat=True).pack(side="left")

        side = tk.Frame(row, bg=t["surface"])
        side.pack(side="right")
        step = C.RETRACT_PRIME_STEP
        self.ret_val = self._small_row(
            side, "RETRACT", lambda: self.ext.set_retract(self.ext.retract_s - step),
            lambda: self.ext.set_retract(self.ext.retract_s + step),
            lambda: self.keypad("Retract time", self.ext.retract_s, "s",
                                C.MIN_RETRACT_PRIME, C.MAX_RETRACT_PRIME, self.ext.set_retract))
        self.pri_val = self._small_row(
            side, "PRIME", lambda: self.ext.set_prime(self.ext.prime_s - step),
            lambda: self.ext.set_prime(self.ext.prime_s + step),
            lambda: self.keypad("Prime time", self.ext.prime_s, "s",
                                C.MIN_RETRACT_PRIME, C.MAX_RETRACT_PRIME, self.ext.set_prime))

        foot = tk.Frame(band, bg=t["surface"])
        foot.pack(fill="x", pady=(4, 0))
        text_label(foot, f"Range {C.EXT_MIN_RPM:g}–{C.EXT_MAX_RPM:g} RPM · tap a number to type it",
                   10, t["faint"], t["surface"], bold=False).pack(side="left")
        reset = text_label(foot, "RESET TIMER", 10, t["muted"], t["surface"])
        reset.pack(side="right")
        reset.bind("<ButtonRelease-1>", lambda _e: self.ext.reset_run_time())

    def _build_feed_band(self, page):
        t = self.t
        band = self.card(page, fill="x", padx=8, pady=(8, 0))
        top, self.feed_pill, self.feed_detail = self._band_top(band, "FEEDER")
        self.feed_ctrl = text_label(top, "", 12, t["muted"], t["surface"])
        self.feed_ctrl.pack(side="left")

        row = tk.Frame(band, bg=t["surface"])
        row.pack(fill="x", pady=(6, 0))
        nudge = lambda d: (lambda: self.feed.set_rpm(self.feed.rpm + d))
        self.btn(row, "−10", nudge(-10), NUDGE_W, NUDGE_H, size=15, repeat=True).pack(side="left")
        self.btn(row, "−1", nudge(-1), NUDGE_W, NUDGE_H, size=15, repeat=True).pack(side="left", padx=4)
        box, self.feed_val = self._value_box(row, "RPM", self.keypad_feed)
        box.pack(side="left")
        self.btn(row, "+1", nudge(1), NUDGE_W, NUDGE_H, size=15, repeat=True).pack(side="left", padx=4)
        self.btn(row, "+10", nudge(10), NUDGE_W, NUDGE_H, size=15, repeat=True).pack(side="left")

        side = tk.Frame(row, bg=t["surface"])
        side.pack(side="right")
        self.ratio_val = self._small_row(
            side, "RATIO", lambda: self.feed.set_ratio(self.feed.ratio - C.RATIO_STEP),
            lambda: self.feed.set_ratio(self.feed.ratio + C.RATIO_STEP),
            lambda: self.keypad("Feed ratio", self.feed.ratio, "×",
                                C.MIN_RATIO, C.MAX_RATIO, self.feed.set_ratio))
        toggles = tk.Frame(side, bg=t["surface"])
        toggles.pack(fill="x", pady=(4, 0))
        self.b_link = self.btn(toggles, "LINK", self.link_toggle, 112, 38, size=12)
        self.b_link.pack(side="left")
        self.b_lock = self.btn(toggles, "RATIO LOCK", self.lock_toggle, 112, 38, size=12)
        self.b_lock.pack(side="right")

        self.feed_info = text_label(band, "", 10, t["faint"], t["surface"], bold=False, anchor="w")
        self.feed_info.pack(fill="x", pady=(4, 0))

    # ---- PROFILES page ----

    def _build_profiles(self, page):
        t = self.t
        hdr = self.header(page)
        text_label(hdr, "Profiles", 18, t["text"], t["surface"]).pack(side="left", padx=12)
        self.prof_count = text_label(hdr, "", 12, t["muted"], t["surface"], bold=False)
        self.prof_count.pack(side="left")
        self.btn(hdr, "＋ NEW FROM CURRENT", self.save_as, 190, 32, "raised", 12).pack(side="right", padx=8)

        body = tk.Frame(page, bg=t["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=8)

        left = tk.Frame(body, bg=t["bg"], width=250)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        self.slots = []
        for i in range(LIST_SLOTS):
            f = tk.Frame(left, bg=t["surface"], height=64, highlightthickness=2,
                         highlightbackground=t["border"], padx=10)
            f.pack(fill="x", pady=(0, 6))
            f.pack_propagate(False)
            name = text_label(f, "", 15, t["text"], t["surface"], anchor="w")
            name.pack(fill="x", pady=(9, 0))
            sub = text_label(f, "", 11, t["muted"], t["surface"], bold=False, anchor="w")
            sub.pack(fill="x")
            for wdg in (f, name, sub):
                wdg.bind("<ButtonPress-1>", lambda _e, i=i: self.select_slot(i))
            self.slots.append((f, name, sub))
        pager = tk.Frame(left, bg=t["bg"])
        pager.pack(fill="x", side="bottom")
        self.b_up = self.btn(pager, "▲", lambda: self.page_list(-1), 70, 34, size=14)
        self.b_up.pack(side="left")
        self.b_down = self.btn(pager, "▼", lambda: self.page_list(1), 70, 34, size=14)
        self.b_down.pack(side="right")
        self.page_label = text_label(pager, "", 11, t["muted"], t["bg"], bold=False)
        self.page_label.pack(side="left", expand=True)

        det = tk.Frame(body, bg=t["surface"], highlightthickness=1,
                       highlightbackground=t["border"], padx=12, pady=10)
        det.pack(side="left", fill="both", expand=True, padx=(10, 0))
        top = tk.Frame(det, bg=t["surface"])
        top.pack(fill="x")
        self.det_name = text_label(top, "", 19, t["text"], t["surface"], anchor="w")
        self.det_name.pack(side="left")
        self.det_star = text_label(top, "", 11, t["accent"], t["surface"])
        self.det_star.pack(side="right")
        self.det_nozzle = text_label(det, "", 12, t["muted"], t["surface"], bold=False, anchor="w")
        self.det_nozzle.pack(fill="x")

        grid = tk.Frame(det, bg=t["surface"])
        grid.pack(fill="x", pady=(6, 0))
        self.det_fields = {}
        for i, (key, cap) in enumerate((("ext", "EXTRUDER"), ("feed", "FEEDER"),
                                        ("ret", "RETRACT"), ("pri", "PRIME"),
                                        ("ratio", "SPEED RATIO"), ("onload", "ON LOAD"))):
            cell = tk.Frame(grid, bg=t["inset"], padx=10, pady=4, width=200, height=50)
            cell.grid(row=i // 2, column=i % 2, padx=(0, 6) if i % 2 == 0 else 0, pady=3, sticky="we")
            cell.pack_propagate(False)
            text_label(cell, cap, 9, t["muted"], t["inset"], anchor="w").pack(fill="x")
            v = text_label(cell, "", 18, t["text"], t["inset"], anchor="w")
            v.pack(fill="x")
            self.det_fields[key] = v
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        self.det_notes = text_label(det, "", 11, t["muted"], t["surface"], bold=False,
                                    anchor="w", justify="left", wraplength=400)
        self.det_notes.pack(fill="x", pady=(4, 0))

        load = self.btn(det, "LOAD  ▶", self.load_selected, 404, 56, "accent", 19)
        load.pack(side="bottom", fill="x", pady=(6, 0))
        acts = tk.Frame(det, bg=t["surface"])
        acts.pack(side="bottom", fill="x")
        self.btn(acts, "EDIT", self.edit_selected, 92, 44, size=12).pack(side="left")
        self.btn(acts, "DUPLICATE", self.duplicate_selected, 100, 44, size=12).pack(side="left", padx=6)
        self.b_default = self.btn(acts, "MAKE\nDEFAULT", self.default_selected, 100, 44, size=11)
        self.b_default.pack(side="left")
        self.b_delete = TouchButton(acts, "DELETE", self.delete_selected, 92, 44, t["raised"],
                                    t["red"], size=12, disabled_bg=t["disabled_bg"],
                                    disabled_fg=t["disabled_fg"])
        self.b_delete.pack(side="right")

    # ---- SETUP page ----

    def _build_setup(self, page):
        t = self.t
        hdr = self.header(page)
        text_label(hdr, "Setup", 18, t["text"], t["surface"]).pack(side="left", padx=12)
        text_label(hdr, f"v{__version__}", 11, t["muted"], t["surface"], bold=False).pack(side="left")

        disp = self.card(page, fill="x", padx=8, pady=(8, 0))
        text_label(disp, "DISPLAY", 10, t["muted"], t["surface"]).pack(anchor="w")
        row = tk.Frame(disp, bg=t["surface"])
        row.pack(fill="x", pady=(6, 0))
        dark = t["name"] == "dark"
        self.btn(row, "☾  DARK", lambda: self.set_theme("dark"), 140, 50,
                 "accent" if dark else "raised", 15).pack(side="left")
        self.btn(row, "☀  LIGHT", lambda: self.set_theme("light"), 140, 50,
                 "raised" if dark else "accent", 15).pack(side="left", padx=6)
        self.b_full = self.btn(row, "", self.toggle_fullscreen, 170, 50, size=13)
        self.b_full.pack(side="left", padx=(20, 0))

        mach = self.card(page, fill="x", padx=8, pady=(8, 0))
        text_label(mach, "MACHINE", 10, t["muted"], t["surface"]).pack(anchor="w")
        row = tk.Frame(mach, bg=t["surface"])
        row.pack(fill="x", pady=(6, 0))
        self.btn(row, "RESET RUN TIMER", self.ext.reset_run_time, 180, 46, size=13).pack(side="left")
        if self.m.simulated:
            self.b_sim = self.btn(row, "", self.sim_toggle_signal, 230, 46, "yellow", 13)
            self.b_sim.pack(side="left", padx=6)

        upd = self.card(page, fill="x", padx=8, pady=(8, 0))
        top = tk.Frame(upd, bg=t["surface"])
        top.pack(fill="x")
        text_label(top, "SOFTWARE UPDATES", 10, t["muted"], t["surface"]).pack(side="left")
        row = tk.Frame(upd, bg=t["surface"])
        row.pack(fill="x", pady=(4, 0))
        self.b_check = self.btn(row, "CHECK NOW", self.check_updates, 130, 40, size=12)
        self.b_check.pack(side="right")
        self.update_status = text_label(row, "", 12, t["text"], t["surface"], bold=False,
                                        anchor="w", justify="left", wraplength=440)
        self.update_status.pack(side="left", fill="x", expand=True)

        info = self.card(page, fill="both", expand=True, padx=8, pady=8)
        text_label(info, "UNITS & LIMITS", 10, t["muted"], t["surface"]).pack(anchor="w")
        lines = (
            f"Speeds are output-shaft RPM.  steps/s = RPM ÷ 60 × steps per rev",
            f"Extruder: {C.EXT_STEPS_PER_OUTPUT_REV:g} steps/rev  ·  "
            f"{C.EXT_MIN_RPM:g}–{C.EXT_MAX_RPM:g} RPM  (old factor 0.20 = 12 RPM)",
            f"Feeder: {C.FEED_STEPS_PER_OUTPUT_REV:g} steps/rev  ·  "
            f"{C.FEED_MIN_RPM:g}–{C.FEED_MAX_RPM:g} RPM  (old factor 1.50 = 90 RPM)",
            f"Profiles: {self.store.path}",
        )
        for line in lines:
            text_label(info, line, 12, t["text"], t["surface"], bold=False,
                       anchor="w").pack(fill="x", pady=1)
        self.btn(info, "QUIT APP", self.quit_confirm, 140, 42, "red", 13).pack(side="bottom", anchor="e")

    # ============================================================
    # ACTIONS
    # ============================================================

    def stop_all(self):
        self.m.stop_all()
        self.notify("STOP ALL — extruder and feeder stopped")

    def feed_start_toggle(self):
        if self.feed.feeding:
            self.feed.stop_feeding()
        else:
            self.feed.start_feeding()

    def feeder_control_toggle(self):
        if self.feed.pi_has_control:
            self.feed.release_control()
            self.notify("Feeder released: front panel in control")
        else:
            self.feed.take_control()
            self.notify("Feeder taken over: Pi in control")

    def link_toggle(self):
        self.feed.set_linked(not self.feed.linked)

    def lock_toggle(self):
        self.feed.set_ratio_lock(not self.feed.ratio_locked)

    def keypad(self, title, value, unit, lo, hi, setter):
        Keypad(self.root, self.t, title, value, unit, lo, hi, setter)

    def keypad_ext(self):
        self.keypad("Extruder speed", self.ext.rpm, "RPM", C.EXT_MIN_RPM, C.EXT_MAX_RPM,
                    self.m.set_ext_rpm)

    def keypad_feed(self):
        self.keypad("Feeder speed", self.feed.rpm, "RPM", C.FEED_MIN_RPM, C.FEED_MAX_RPM,
                    self.feed.set_rpm)

    def set_theme(self, name):
        if name != self.t["name"]:
            self.settings["theme"] = name
            self.build()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def sim_toggle_signal(self):
        self.m.gpio.write(C.EXT_SIGNAL_PIN, 0 if self.ext.omnicore_signal else 1)

    def quit_confirm(self):
        Confirm(self.root, self.t, "Quit WASP Control?",
                "Both motors stop and the feeder relay returns control to the front panel.",
                "QUIT", self.root.destroy, danger=True)

    def on_error(self, exc_type, exc, tb):
        """Button handler crashed: show it on screen, not just in a terminal."""
        import traceback
        traceback.print_exception(exc_type, exc, tb)
        self.notify(f"Error: {exc}"[:70], error=True)

    def notify(self, text, error=False):
        t = self.t
        self.toast.configure(text=text, bg=t["red"] if error else t["accent"],
                             fg=t["red_fg"] if error else t["accent_fg"])
        self.toast.place(relx=0.5, rely=1.0, y=-96, anchor="s")
        self.toast.lift()
        if self._toast_job:
            self.root.after_cancel(self._toast_job)
        self._toast_job = self.root.after(6000 if error else 2500, self.toast.place_forget)

    # ---- profiles ----

    def _name_check(self, keep=None):
        def check(values):
            name = values["name"]
            if not name:
                return "Give the profile a name."
            clash = self.store.get(name)
            if clash and (keep is None or clash["name"].lower() != keep.lower()):
                return f"“{clash['name']}” already exists — pick another name."
            return None
        return check

    def save_current(self):
        if not self.current or not self.store.get(self.current):
            self.save_as()
            return
        self.store.put(self.current, self.m.snapshot())
        self.notify(f"Saved “{self.current}”")

    def save_as(self):
        cur = self.store.get(self.current) if self.current else None
        snap = self.m.snapshot()
        subtitle = (f"Ext {snap['ext_rpm']:g} RPM · Feed {snap['feed_rpm']:g} RPM · "
                    f"{snap['ratio']:g}× · {snap['retract_s']:.2f} / {snap['prime_s']:.2f} s")

        def done(values, make_default):
            p = self.store.put(values["name"], snap, nozzle=values["nozzle"], notes=values["notes"])
            if make_default:
                self.store.set_default(p["name"])
            self.current = self.selected = p["name"]
            self.refresh_profiles()
            self.notify(f"Saved new profile “{p['name']}”")

        TextForm(self.root, self.t, "Save as new profile",
                 [[("name", "Profile name", "", 24), ("nozzle", "Nozzle", cur["nozzle"] if cur else "", 9)],
                  [("notes", "Notes (optional)", "", 50)]],
                 done, ok_text="SAVE PROFILE", toggle=("Make this the default", False),
                 validate=self._name_check(), subtitle=subtitle,
                 limits={"name": MAX_NAME_LEN, "nozzle": 12, "notes": 90})

    def edit_selected(self):
        p = self.store.get(self.selected)
        if not p:
            return
        old = p["name"]

        def done(values, _toggle):
            self.store.rename(old, values["name"])
            p2 = self.store.get(values["name"])
            p2["nozzle"], p2["notes"] = values["nozzle"], values["notes"]
            self.store.save()
            if self.current == old:
                self.current = p2["name"]
            self.selected = p2["name"]
            self.refresh_profiles()

        TextForm(self.root, self.t, "Edit profile",
                 [[("name", "Profile name", p["name"], 24), ("nozzle", "Nozzle", p["nozzle"], 9)],
                  [("notes", "Notes", p["notes"], 50)]],
                 done, ok_text="SAVE", validate=self._name_check(keep=old),
                 limits={"name": MAX_NAME_LEN, "nozzle": 12, "notes": 90})

    def duplicate_selected(self):
        p = self.store.duplicate(self.selected)
        if p:
            self.selected = p["name"]
            self.refresh_profiles()

    def default_selected(self):
        self.store.set_default(self.selected)
        self.list_offset = 0
        self.refresh_profiles()
        self.notify(f"“{self.selected}” now loads on startup")

    def delete_selected(self):
        name = self.selected

        def go():
            if self.store.delete(name):
                if self.current and self.current.lower() == name.lower():
                    self.current = None
                self.selected = self.store.default_name
                self.refresh_profiles()

        Confirm(self.root, self.t, "Delete profile?",
                f"“{name}” will be removed permanently.", "DELETE", go, danger=True)

    def load_selected(self):
        p = self.store.get(self.selected)
        if not p:
            return
        self.m.apply_profile(p)
        self.store.touch(p["name"])
        self.current = p["name"]
        self.show("run")
        self.notify(f"Loaded “{p['name']}”")

    def select_slot(self, i):
        items = self.store.ordered()
        idx = self.list_offset + i
        if idx < len(items):
            self.selected = items[idx]["name"]
            self.refresh_profiles()

    def page_list(self, direction):
        n = len(self.store.profiles)
        self.list_offset = max(0, min(self.list_offset + direction * LIST_SLOTS,
                                      ((n - 1) // LIST_SLOTS) * LIST_SLOTS))
        self.refresh_profiles()

    def refresh_profiles(self):
        t = self.t
        items = self.store.ordered()
        if not self.store.get(self.selected):
            self.selected = self.store.default_name
        default = self.store.default()
        n = len(items)
        self.prof_count.configure(text=f"{n} saved")
        for i, (f, name, sub) in enumerate(self.slots):
            idx = self.list_offset + i
            if idx >= n:
                f.configure(bg=t["bg"], highlightbackground=t["bg"])
                name.configure(text="", bg=t["bg"])
                sub.configure(text="", bg=t["bg"])
                continue
            p = items[idx]
            sel = p["name"] == self.selected
            bg = t["inset"] if sel else t["surface"]
            border = t["accent"] if sel else t["border"]
            is_def = p is default
            f.configure(bg=bg, highlightbackground=border)
            name.configure(text=("★ " if is_def else "") + p["name"], bg=bg,
                           fg=t["accent"] if is_def else t["text"])
            if is_def:
                info = "Default · loads on startup"
            elif p["last_used"]:
                info = "Last used " + time.strftime("%b %d  %H:%M", time.localtime(p["last_used"]))
            else:
                info = "Never used"
            if p["nozzle"]:
                info = f"{p['nozzle']} · {info}"
            sub.configure(text=info, bg=bg)
        last = min(self.list_offset + LIST_SLOTS, n)
        self.page_label.configure(text=f"{self.list_offset + 1}–{last} of {n}")
        self.b_up.set(enabled=self.list_offset > 0)
        self.b_down.set(enabled=last < n)

        p = self.store.get(self.selected)
        self.det_name.configure(text=p["name"])
        self.det_star.configure(text="★ DEFAULT" if p is default else "")
        self.det_nozzle.configure(text=f"Nozzle: {p['nozzle']}" if p["nozzle"] else "Nozzle: —")
        self.det_fields["ext"].configure(text=f"{p['ext_rpm']:.1f} RPM")
        self.det_fields["feed"].configure(text=f"{p['feed_rpm']:.1f} RPM")
        self.det_fields["ret"].configure(text=f"{p['retract_s']:.2f} s")
        self.det_fields["pri"].configure(text=f"{p['prime_s']:.2f} s")
        self.det_fields["ratio"].configure(text=f"{p['ratio']:g}×")
        on_load = []
        if p["link"]:
            on_load.append("Link ✓")
        if p["ratio_lock"]:
            on_load.append("Lock ✓")
        self.det_fields["onload"].configure(text=" · ".join(on_load) or "—")
        self.det_notes.configure(text=p["notes"])
        self.b_default.set(enabled=p is not default)
        self.b_delete.set(enabled=n > 1)

    # ============================================================
    # PERIODIC REDRAW
    # ============================================================

    def poll(self, schedule=True):
        try:
            self._update_run()
            self._update_badge()
            if self.page == "setup":
                self._update_setup()
        finally:
            if schedule:
                self.root.after(POLL_MS, self.poll)

    def _status(self, pill, text, colour):
        t = self.t
        pill.set(text, t[colour], t[colour + "_fg"])

    def _update_run(self):
        t = self.t
        ext, feed = self.ext, self.feed

        # Header
        p = self.store.get(self.current) if self.current else None
        set_label(self.run_name, text=p["name"] if p else "No profile loaded")
        if p and not same_settings(p, self.m.snapshot()):
            self.run_modified.set("● unsaved changes", t["chip_warn_bg"], t["chip_warn_fg"])
        else:
            self.run_modified.set("", t["surface"], t["surface"])
        if ext.omnicore_signal:
            self.omni_pill.set("● OmniCore HIGH", t["green"], t["green_fg"])
        else:
            self.omni_pill.set("● OmniCore LOW", t["raised"], t["raised_fg"])

        # Extruder
        colour = {Extruder.STOPPED: "red", Extruder.PRIMING: "yellow",
                  Extruder.EXTRUDING: "green", Extruder.RETRACTING: "yellow"}[ext.state]
        self._status(self.ext_pill, ext.state, colour)
        rt = ext.get_run_time()
        set_label(self.ext_timer, text=f"⏱ {int(rt // 60)}:{int(rt % 60):02d}")
        set_label(self.ext_val, text=f"{ext.rpm:.1f}")
        hz = rpm_to_hz(ext.rpm, C.EXT_STEPS_PER_OUTPUT_REV)
        set_label(self.ext_detail, text=f"{ext.rpm / 60:.4f} rev/s · {hz:.0f} steps/s")
        set_label(self.ret_val, text=f"{ext.retract_s:.2f}s")
        set_label(self.pri_val, text=f"{ext.prime_s:.2f}s")

        # Extruder buttons
        if ext.manual_override:
            self.b_manual.set("MANUAL\nON", t["yellow"], t["yellow_fg"])
            if ext.manual_running:
                self.b_start.set("RUNNING", t["green"], t["green_fg"], enabled=True)
            else:
                self.b_start.set("START", t["raised"], t["raised_fg"], enabled=True)
            self.b_stop.set("STOP", t["red"], t["red_fg"])
        else:
            self.b_manual.set("MANUAL", t["raised"], t["raised_fg"])
            self.b_start.set("START", t["raised"], t["raised_fg"], enabled=False)
            if ext.omnicore_signal and ext.override_stop:
                self.b_stop.set("OVERRIDE\nACTIVE", t["yellow"], t["yellow_fg"])
            elif ext.omnicore_signal:
                self.b_stop.set("OVERRIDE\nSTOP", t["red"], t["red_fg"])
            else:
                self.b_stop.set("STOP", t["red"], t["red_fg"])

        # Feeder
        colour = {Feeder.IDLE: "gray", Feeder.PI_CONTROL: "yellow", Feeder.FEEDING: "green"}[feed.state]
        self._status(self.feed_pill, feed.state, colour)
        if feed.pi_has_control:
            set_label(self.feed_ctrl, text="PI IN CONTROL", fg=t["green"])
            self.b_control.set("RELEASE\nFEEDER", t["yellow"], t["yellow_fg"])
        else:
            set_label(self.feed_ctrl, text="FRONT PANEL", fg=t["muted"])
            self.b_control.set("TAKE\nCONTROL", t["green"], t["green_fg"])
        set_label(self.feed_val, text=f"{feed.rpm:.1f}")
        hz = rpm_to_hz(feed.rpm, C.FEED_STEPS_PER_OUTPUT_REV)
        set_label(self.feed_detail, text=f"{feed.rpm / 60:.3f} rev/s · {hz:.0f} steps/s")
        set_label(self.ratio_val, text=f"{feed.ratio:g}×")
        if feed.feeding:
            self.b_feedstart.set("FEEDING", t["green"], t["green_fg"], enabled=True)
        else:
            self.b_feedstart.set("START\nFEED", t["raised"], t["raised_fg"],
                                 enabled=feed.pi_has_control)
        if feed.linked:
            self.b_link.set("LINKED ✓", t["green"], t["green_fg"])
        else:
            self.b_link.set("LINK", t["raised"], t["raised_fg"])
        if feed.ratio_locked:
            self.b_lock.set("LOCKED ✓", t["green"], t["green_fg"])
        else:
            self.b_lock.set("RATIO LOCK", t["raised"], t["raised_fg"])

        info = []
        if feed.linked:
            info.append("Linked: feeds whenever the extruder runs"
                        if not feed.feeding else "Linked: feeding with the extruder")
        if feed.ratio_locked:
            info.append(f"+1 RPM extruder → +{feed.ratio:g} RPM feeder")
        set_label(self.feed_info, text="   ·   ".join(info) or "Not linked: feeder runs only from START FEED")

    def _update_setup(self):
        t = self.t
        self._update_setup_status()
        self.b_full.set("FULLSCREEN: ON" if self.fullscreen else "FULLSCREEN: OFF")
        if self.m.simulated:
            on = self.ext.omnicore_signal
            self.b_sim.set(f"SIM OmniCore: {'HIGH' if on else 'LOW'}",
                           t["green"] if on else t["yellow"],
                           t["green_fg"] if on else t["yellow_fg"])

    # ---- update check ----

    def check_updates(self):
        """Ask GitHub (on a thread) whether a newer version exists. Only
        reports; installing is done with the Update WASP Control icon."""
        if not self.update_checker:
            return
        if self.update_info and self.update_info["status"] == U.CHECKING:
            return
        self.update_info = {"status": U.CHECKING}

        def work():
            # Assigning one attribute is atomic; poll() picks it up.
            self.update_info = self.update_checker()

        threading.Thread(target=work, daemon=True).start()

    def _periodic_check(self):
        self.check_updates()
        self.root.after(U.CHECK_EVERY_S * 1000, self._periodic_check)

    def _update_label(self):
        info = self.update_info
        if not info:
            return None
        if info["status"] == U.AVAILABLE:
            remote = info["remote_version"]
            new = f"v{remote}" if remote and remote != __version__ else "Newer changes"
            return f"{new} is available."
        return None

    def _update_badge(self):
        available = self._update_label()
        if available:
            self.update_badge.configure(bg=self.nav["setup"].cget("bg"))
            self.update_badge.place(relx=1.0, x=-6, y=2, anchor="ne")
            if not self._update_announced:
                self._update_announced = True
                self.notify(f"{available} See Setup.")
        else:
            self.update_badge.place_forget()

    def _update_setup_status(self):
        t = self.t
        info = self.update_info
        status = info["status"] if info else None
        when = ""
        if info and info.get("checked"):
            when = time.strftime("%H:%M", time.localtime(info["checked"]))
        if not self.update_checker:
            text, fg = "Update checks are off.", t["muted"]
        elif status is None or status == U.CHECKING:
            text, fg = "Checking GitHub for updates…", t["muted"]
        elif status == U.AVAILABLE:
            text = (f"{self._update_label()} Quit the app, then tap the "
                    f"“Update WASP Control” icon on the desktop.")
            fg = t["green"]
        elif status == U.CURRENT:
            text, fg = f"Up to date (v{__version__}). Checked {when}.", t["text"]
        elif status == U.OFFLINE:
            text, fg = f"Couldn't reach GitHub (no internet?). Tried {when}.", t["muted"]
        else:
            text, fg = "Not installed with git, so updates can't be checked.", t["muted"]
        set_label(self.update_status, text=text, fg=fg)
        self.b_check.set(enabled=bool(self.update_checker) and status != U.CHECKING)

    def run(self):
        self.root.mainloop()
