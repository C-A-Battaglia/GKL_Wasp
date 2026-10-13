"""
Touch-friendly widgets built from plain Tk Frames and Labels.

tk.Button misbehaves on touchscreens (sticky "active" colours, focus rings,
no hold-to-repeat), so buttons here are Labels with their own press logic.
Dialogs are overlays placed over the main window instead of Toplevels, so
they work in fullscreen kiosk mode without a window manager getting involved.
"""

import tkinter as tk

from .theme import font

REPEAT_DELAY_MS = 450
REPEAT_EVERY_MS = 110


def shade(hex_colour, amount=0.22):
    """Pressed-state colour: move toward black (or white for very dark colours)."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    target = 255 if (r + g + b) < 120 else 0
    mix = lambda c: int(c + (target - c) * amount)
    return "#%02x%02x%02x" % (mix(r), mix(g), mix(b))


class TouchButton(tk.Frame):
    """Fixed-size button.

    repeat=True        fires on press and keeps firing while held (nudges)
    fire_on_press=True fires immediately on touch (STOP buttons)
    otherwise          fires on release, only if the finger is still on it
    """

    def __init__(self, parent, text, command, w, h, bg, fg, size=14,
                 repeat=False, fire_on_press=False, enabled=True,
                 disabled_bg=None, disabled_fg=None, bold=True):
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.command = command
        self.repeat = repeat
        self.fire_on_press = fire_on_press
        self._bg, self._fg = bg, fg
        self._dis_bg = disabled_bg or bg
        self._dis_fg = disabled_fg or fg
        self._enabled = enabled
        self._job = None
        self._pressed = False
        self.label = tk.Label(self, text=text, font=font(size, bold), bg=bg, fg=fg,
                              justify="center", bd=0, highlightthickness=0)
        self.label.pack(fill="both", expand=True)
        for wdg in (self, self.label):
            wdg.bind("<ButtonPress-1>", self._press)
            wdg.bind("<ButtonRelease-1>", self._release)
        self._paint()

    def _paint(self):
        if not self._enabled:
            bg, fg = self._dis_bg, self._dis_fg
        elif self._pressed:
            bg, fg = shade(self._bg), self._fg
        else:
            bg, fg = self._bg, self._fg
        if self.cget("bg") != bg:
            self.configure(bg=bg)
            self.label.configure(bg=bg)
        if self.label.cget("fg") != fg:
            self.label.configure(fg=fg)

    def set(self, text=None, bg=None, fg=None, enabled=None):
        if text is not None and self.label.cget("text") != text:
            self.label.configure(text=text)
        if bg is not None:
            self._bg = bg
        if fg is not None:
            self._fg = fg
        if enabled is not None:
            self._enabled = enabled
        self._paint()

    def _fire(self):
        if self._enabled and self.command:
            self.command()

    def _press(self, _event):
        if not self._enabled:
            return
        self._pressed = True
        self._paint()
        if self.repeat or self.fire_on_press:
            self._fire()
        if self.repeat:
            self._job = self.after(REPEAT_DELAY_MS, self._repeat)

    def _repeat(self):
        if self._pressed:
            self._fire()
            self._job = self.after(REPEAT_EVERY_MS, self._repeat)

    def _release(self, event):
        was_pressed = self._pressed
        self._pressed = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._paint()
        if was_pressed and not (self.repeat or self.fire_on_press):
            under = self.winfo_containing(event.x_root, event.y_root)
            if under in (self, self.label):
                self._fire()


def text_label(parent, text, size, fg, bg, bold=True, **kw):
    return tk.Label(parent, text=text, font=font(size, bold), fg=fg, bg=bg, bd=0, **kw)


def set_label(label, **kw):
    """Configure a label only where values changed (avoids redraw flicker)."""
    changed = {k: v for k, v in kw.items() if str(label.cget(k)) != str(v)}
    if changed:
        label.configure(**changed)


class Pill(tk.Frame):
    """Small coloured status tag."""

    def __init__(self, parent, text, bg, fg, size=11, padx=9, pady=3):
        super().__init__(parent, bg=bg, padx=padx, pady=pady)
        self.label = text_label(self, text, size, fg, bg)
        self.label.pack()

    def set(self, text, bg, fg):
        if self.cget("bg") != bg:
            self.configure(bg=bg)
        set_label(self.label, text=text, bg=bg, fg=fg)


# ============================================================
# OVERLAY DIALOGS
# ============================================================

class Overlay(tk.Frame):
    """Covers the whole window; subclasses fill self.panel."""

    def __init__(self, root, theme, width, title):
        super().__init__(root, bg="#000000")
        self.t = theme
        self.place(x=0, y=0, relwidth=1, relheight=1)
        self.panel = tk.Frame(self, bg=theme["surface"], padx=14, pady=10,
                              highlightthickness=2, highlightbackground=theme["accent"])
        self.panel.place(relx=0.5, rely=0.5, anchor="center", width=width)
        head = tk.Frame(self.panel, bg=theme["surface"])
        head.pack(fill="x")
        text_label(head, title, 17, theme["text"], theme["surface"]).pack(side="left")
        self.head = head
        self.lift()

    def close(self):
        self.destroy()


class Keypad(Overlay):
    """Numeric entry. on_ok receives a float (caller clamps)."""

    def __init__(self, root, theme, title, value, unit, lo, hi, on_ok):
        super().__init__(root, theme, 420, title)
        t = theme
        self.on_ok = on_ok
        self.text = f"{value:g}"
        self.fresh = True  # first key replaces the old value
        text_label(self.head, f"{lo:g} – {hi:g} {unit}", 12, t["muted"], t["surface"],
                   bold=False).pack(side="right")

        disp = tk.Frame(self.panel, bg=t["inset"], height=58)
        disp.pack(fill="x", pady=(8, 8))
        disp.pack_propagate(False)
        self.disp = text_label(disp, self.text, 34, t["text"], t["inset"])
        self.disp.pack(side="left", padx=12)
        text_label(disp, unit, 15, t["muted"], t["inset"]).pack(side="left")

        grid = tk.Frame(self.panel, bg=t["surface"])
        grid.pack()
        keys = ["7", "8", "9", "⌫", "4", "5", "6", "C", "1", "2", "3", "", "0", ".", "", ""]
        for i, k in enumerate(keys):
            if not k:
                continue
            TouchButton(grid, k, lambda k=k: self.key(k), 90, 52, t["raised"], t["raised_fg"],
                        size=20).grid(row=i // 4, column=i % 4, padx=3, pady=3)
        TouchButton(grid, "OK", self.ok, 90, 110, t["accent"], t["accent_fg"],
                    size=18).grid(row=2, column=3, rowspan=2, padx=3, pady=3)
        TouchButton(self.panel, "CANCEL", self.close, 384, 46, t["raised"], t["raised_fg"],
                    size=14).pack(pady=(6, 2))

    def key(self, k):
        if k == "C":
            self.text = ""
        elif k == "⌫":
            self.text = "" if self.fresh else self.text[:-1]
        else:
            if self.fresh:
                self.text = ""
            if k == "." and "." in self.text:
                return
            if len(self.text) < 7:
                self.text += k
        self.fresh = False
        self.disp.configure(text=self.text or "0")

    def ok(self):
        try:
            value = float(self.text)
        except ValueError:
            self.close()
            return
        self.close()
        self.on_ok(value)


KEY_ROWS = ["1234567890", "QWERTYUIOP", "ASDFGHJKL-", "ZXCVBNM.()"]


class TextForm(Overlay):
    """On-screen keyboard form.

    fields:    rows of fields; each row is a list of (key, label, initial_text, width_chars)
    toggle:    optional (label, initial_bool) shown as a checkbox button
    validate:  fn(values) -> error string or None
    on_ok:     fn(values, toggle_value)
    """

    def __init__(self, root, theme, title, fields, on_ok, ok_text="SAVE",
                 toggle=None, validate=None, subtitle="", limits=None):
        super().__init__(root, theme, 780, title)
        t = theme
        self.on_ok = on_ok
        self.validate = validate
        self.limits = limits or {}
        flat = [f for row in fields for f in row]
        self.values = {f[0]: f[2] for f in flat}
        self.active = flat[0][0]
        self.shift = True
        self.toggle_val = toggle[1] if toggle else None
        if subtitle:
            text_label(self.head, subtitle, 11, t["muted"], t["surface"], bold=False).pack(side="right")

        self.field_widgets = {}
        for row in fields:
            frow = tk.Frame(self.panel, bg=t["surface"])
            frow.pack(fill="x", pady=(5, 0))
            for i, (key, label, _, width) in enumerate(row):
                box = tk.Frame(frow, bg=t["inset"], highlightthickness=2, padx=8, pady=1)
                box.pack(side="left", fill="x", expand=(i == 0), padx=(0 if i == 0 else 6, 0))
                cap = text_label(box, label.upper(), 9, t["muted"], t["inset"])
                cap.pack(anchor="w")
                val = text_label(box, "", 16, t["text"], t["inset"], anchor="w", width=width)
                val.pack(anchor="w", fill="x")
                for wdg in (box, cap, val):
                    wdg.bind("<ButtonPress-1>", lambda _e, k=key: self.focus_field(k))
                self.field_widgets[key] = (box, val)

        self.error = text_label(self.panel, "", 11, t["red"], t["surface"])
        self.error.pack(anchor="w")

        kb = tk.Frame(self.panel, bg=t["inset"], padx=4, pady=4)
        kb.pack(fill="x")
        self.letter_buttons = []
        for r, row in enumerate(KEY_ROWS):
            line = tk.Frame(kb, bg=t["inset"])
            line.pack(pady=2)
            if r == 3:
                self.shift_btn = TouchButton(line, "⇧", self.toggle_shift, 72, 40,
                                             t["raised"], t["raised_fg"], size=18)
                self.shift_btn.pack(side="left", padx=2)
            for ch in row:
                b = TouchButton(line, ch, lambda c=ch: self.type(c), 62, 40,
                                t["surface"], t["text"], size=17)
                b.pack(side="left", padx=2)
                if ch.isalpha():
                    self.letter_buttons.append((b, ch))
            if r == 0:
                TouchButton(line, "⌫", self.backspace, 72, 40, t["raised"], t["raised_fg"],
                            size=17, repeat=True).pack(side="left", padx=2)
        line = tk.Frame(kb, bg=t["inset"])
        line.pack(pady=2)
        TouchButton(line, "SPACE", lambda: self.type(" "), 420, 36, t["surface"], t["muted"],
                    size=12).pack(side="left", padx=2)
        TouchButton(line, "CLEAR", self.clear, 110, 36, t["raised"], t["raised_fg"],
                    size=12).pack(side="left", padx=2)

        acts = tk.Frame(self.panel, bg=t["surface"])
        acts.pack(fill="x", pady=(8, 2))
        TouchButton(acts, "CANCEL", self.close, 150, 48, t["raised"], t["raised_fg"],
                    size=14).pack(side="left")
        if toggle:
            self.toggle_btn = TouchButton(acts, "", self.flip_toggle, 250, 48, t["raised"],
                                          t["raised_fg"], size=13)
            self.toggle_btn.pack(side="left", padx=8)
            self.toggle_label = toggle[0]
            self._paint_toggle()
        TouchButton(acts, ok_text, self.ok, 230, 48, t["accent"], t["accent_fg"],
                    size=16).pack(side="right")
        self.focus_field(self.active)
        self._paint_shift()

    def focus_field(self, key):
        self.active = key
        for k, (box, _) in self.field_widgets.items():
            box.configure(highlightbackground=self.t["accent"] if k == key else self.t["border"],
                          highlightcolor=self.t["accent"] if k == key else self.t["border"])
        self._refresh()

    def _refresh(self):
        for k, (_, val) in self.field_widgets.items():
            caret = "▏" if k == self.active else ""
            val.configure(text=self.values[k] + caret)

    def _paint_shift(self):
        self.shift_btn.set(bg=self.t["accent"] if self.shift else self.t["raised"],
                           fg=self.t["accent_fg"] if self.shift else self.t["raised_fg"])
        for b, ch in self.letter_buttons:
            b.set(text=ch.upper() if self.shift else ch.lower())

    def _paint_toggle(self):
        mark = "☑" if self.toggle_val else "☐"
        self.toggle_btn.set(text=f"{mark}  {self.toggle_label}")

    def flip_toggle(self):
        self.toggle_val = not self.toggle_val
        self._paint_toggle()

    def toggle_shift(self):
        self.shift = not self.shift
        self._paint_shift()

    def type(self, ch):
        if ch.isalpha():
            ch = ch.upper() if self.shift else ch.lower()
            if self.shift:
                self.shift = False
                self._paint_shift()
        limit = self.limits.get(self.active, 32)
        if len(self.values[self.active]) < limit:
            self.values[self.active] += ch
        self._refresh()

    def backspace(self):
        self.values[self.active] = self.values[self.active][:-1]
        self._refresh()

    def clear(self):
        self.values[self.active] = ""
        self._refresh()

    def ok(self):
        values = {k: v.strip() for k, v in self.values.items()}
        err = self.validate(values) if self.validate else None
        if err:
            self.error.configure(text=err)
            return
        self.close()
        self.on_ok(values, self.toggle_val)


class Confirm(Overlay):
    def __init__(self, root, theme, title, message, ok_text, on_ok, danger=False):
        super().__init__(root, theme, 460, title)
        t = theme
        text_label(self.panel, message, 14, t["muted"], t["surface"], bold=False,
                   wraplength=420, justify="left").pack(anchor="w", pady=(10, 14))
        row = tk.Frame(self.panel, bg=t["surface"])
        row.pack(fill="x")
        TouchButton(row, "CANCEL", self.close, 200, 52, t["raised"], t["raised_fg"],
                    size=14).pack(side="left")

        def go():
            self.close()
            on_ok()
        TouchButton(row, ok_text, go, 200, 52, t["red"] if danger else t["accent"],
                    t["red_fg"] if danger else t["accent_fg"], size=14).pack(side="right")
