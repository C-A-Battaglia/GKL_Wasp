#!/usr/bin/env python3
"""
WASP Clay Extruder + Continuous Feeder Controller
Raspberry Pi 5 touchscreen - CraftLab, University of Houston

  python3 wasp_control.py                 # on the Pi
  python3 wasp_control.py --fullscreen    # kiosk mode (Esc / F11 toggles)
  python3 wasp_control.py --sim           # desk testing without GPIO

GPIO pin map: see wasp/config.py
"""

import argparse
import os

from wasp import __version__
from wasp import config as C
from wasp.gpio import open_backend
from wasp.motion import Machine
from wasp.profiles import ProfileStore, Settings


def main():
    ap = argparse.ArgumentParser(description="WASP extruder + feeder controller")
    ap.add_argument("--sim", action="store_true", help="simulate GPIO (no hardware)")
    ap.add_argument("--fullscreen", action="store_true", help="start fullscreen")
    ap.add_argument("--data-dir", default=os.path.expanduser("~/.wasp_control"),
                    help="where profiles.json and settings.json live")
    args = ap.parse_args()

    print(f"WASP Control v{__version__}  -  CraftLab, University of Houston")
    gpio = open_backend(C.GPIO_CHIP, force_sim=args.sim)
    machine = Machine(gpio)
    store = ProfileStore(args.data_dir)
    settings = Settings(args.data_dir)

    # Start on the default profile's speeds so OmniCore never drives the
    # extruder with stale values; linking waits until a profile is loaded.
    machine.apply_profile(store.default(), links=False)
    machine.start()
    print(f"Profiles: {store.path}  ({len(store.profiles)} saved)")

    from wasp.ui.app import App
    app = App(machine, store, settings, fullscreen=args.fullscreen)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    finally:
        machine.shutdown()
        print("Motors stopped, feeder relay released. Bye.")


if __name__ == "__main__":
    main()
