#!/usr/bin/env python3
"""
Render the real Tk GUI (simulated GPIO) and save screenshots of each page in
both themes. Needs an X display; on a headless box run:

    xvfb-run -s "-screen 0 800x480x24" python3 tools/screenshots.py docs/screens
"""

import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from wasp import config as C            # noqa: E402
from wasp.gpio import SimBackend        # noqa: E402
from wasp.motion import Machine         # noqa: E402
from wasp.profiles import ProfileStore, Settings  # noqa: E402
from wasp.ui.app import App             # noqa: E402

SAMPLES = [
    ("6 mm Stoneware", "6 mm", 4.5, 54, 7.5, 0.40, 0.35, True, True, "1.2 mm layers, TCP 40 mm/s"),
    ("4 mm Porcelain fine", "4 mm", 2.4, 30, 5.0, 0.30, 0.30, True, False, ""),
    ("8 mm Terracotta", "8 mm", 18.0, 120, 3.0, 0.60, 0.50, False, False, ""),
    ("3 mm Slow test", "3 mm", 0.4, 6, 10.0, 0.20, 0.20, False, False, "Below the old 0.1 limit"),
    ("5 mm Paper clay", "5 mm", 6.0, 60, 6.0, 0.45, 0.40, True, True, ""),
    ("6 mm B-Mix v2", "6 mm", 5.0, 58, 7.5, 0.40, 0.35, True, True, ""),
]


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    data = tempfile.mkdtemp()
    store = ProfileStore(data)
    for i, (name, noz, e, f, r, ret, pri, link, lock, notes) in enumerate(SAMPLES):
        store.put(name, dict(ext_rpm=e, feed_rpm=f, ratio=r, retract_s=ret, prime_s=pri,
                             link=link, ratio_lock=lock), nozzle=noz, notes=notes)
        store.get(name)["last_used"] = time.time() - i * 86400
    store.save()
    settings = Settings(data)
    gpio = SimBackend()
    machine = Machine(gpio)
    machine.apply_profile(store.default(), links=False)
    machine.start()
    app = App(machine, store, settings)
    root = app.root

    def snap(name):
        root.update()
        time.sleep(0.4)
        root.update()
        path = os.path.join(out_dir, name + ".png")
        subprocess.run(["import", "-window", "root", "-crop", "800x480+0+0", path],
                       check=True)
        print("wrote", path)

    def scenario():
        for theme in ("dark", "light"):
            settings["theme"] = theme
            app.page = "profiles"
            app.selected = "6 mm Stoneware"
            app.build()
            snap(f"{theme}_1_profiles")
            app.load_selected()
            gpio.write(C.EXT_SIGNAL_PIN, 1)       # robot says extrude
            time.sleep(0.8)
            machine.set_ext_rpm(4.7)              # operator nudges -> "unsaved changes"
            app.toast.place_forget()
            app.poll(schedule=False)
            snap(f"{theme}_2_run")
            app.save_as()
            snap(f"{theme}_3_save_as")
            close_overlays()
            app.keypad_ext()
            snap(f"{theme}_4_keypad")
            close_overlays()
            app.show("setup")
            app.poll(schedule=False)
            snap(f"{theme}_5_setup")
            gpio.write(C.EXT_SIGNAL_PIN, 0)
            time.sleep(1.2)
        root.destroy()

    def close_overlays():
        from wasp.ui.widgets import Overlay
        for w in list(root.winfo_children()):
            if isinstance(w, Overlay):
                w.close()

    root.after(500, scenario)
    app.run()
    machine.shutdown()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/screens")
