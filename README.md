# GKL_Wasp

Touchscreen controller for a **WASP clay extruder + continuous feeder** on a
Raspberry Pi 5. The extruder is driven by the **ABB GoFa / OmniCore** on/off
signal. CraftLab, University of Houston.

| Dark | Light |
|---|---|
| ![](docs/screens/dark_2_run.png) | ![](docs/screens/light_2_run.png) |
| ![](docs/screens/dark_1_profiles.png) | ![](docs/screens/light_1_profiles.png) |

## What it does

- **Profiles:** once you've tuned feed and speed for a nozzle, save the
  settings as a named profile. The app opens on the profile list, with the
  ★ default at the top. Each profile stores:
  - extruder RPM and feeder RPM
  - feed ratio
  - retract and prime times
  - whether Link and Ratio Lock are on
  - nozzle and notes
- **Real RPM:** both motors show output-shaft RPM. The extruder now goes down
  to 0.1 RPM (the old minimum was 6 RPM). Nudge buttons step by ±0.1/±1 on the
  extruder and ±1/±10 on the feeder; hold one down to repeat. Tap any number
  to type an exact value.
- **STOP ALL:** on the side rail on every page.
  - Stops the extruder. If OmniCore is HIGH, it holds an override stop until
    the robot's signal drops.
  - Stops and unlinks the feeder. The Pi keeps the relay so the front panel
    can't restart the feeder.
- **Dark / light theme:** switch on the Setup page. The choice is remembered.
- **Feeder takeover:** TAKE CONTROL switches the relay from the feeder's front
  panel to the Pi. LINK makes the feeder run whenever the extruder runs.
  RATIO LOCK makes the feeder follow extruder speed changes (feeder change =
  extruder change × ratio).

## Install on the Pi (Raspberry Pi OS Bookworm)

```bash
sudo apt install python3-tk python3-lgpio
git clone https://github.com/C-A-Battaglia/GKL_Wasp.git
cd GKL_Wasp
python3 wasp_control.py --fullscreen
```

Esc or F11 toggles fullscreen. Profiles and settings are saved in
`~/.wasp_control/` (`profiles.json`, `settings.json`).

### Start automatically on boot

Create `~/.config/autostart/wasp.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=WASP Control
Exec=python3 /home/pi/GKL_Wasp/wasp_control.py --fullscreen
```

## Testing without hardware

```bash
python3 wasp_control.py --sim
```

`--sim` replaces GPIO with a simulator. The Setup page then has a button that
toggles a fake OmniCore signal. To run the tests:

```bash
pip install pytest
python3 -m pytest tests                    # GUI test runs when a display is available
xvfb-run python3 tools/screenshots.py      # regenerate docs/screens
```

## Layout

| Path | |
|---|---|
| `wasp_control.py` | entry point |
| `wasp/config.py` | GPIO pins, motor constants, speed limits |
| `wasp/gpio.py` | lgpio wrapper and simulator |
| `wasp/motion.py` | stepper, extruder state machine, feeder, STOP ALL |
| `wasp/profiles.py` | profile and settings storage (JSON, crash-safe writes) |
| `wasp/ui/` | Tkinter GUI: theme, touch widgets, pages |
| `legacy/WASP3326.py` | the previous single-file version, kept for reference |
| `mockups/` | design concepts A/B/C |

## Units and limits

`steps/s = RPM ÷ 60 × steps per output rev`

| Motor | Steps per output rev | Range |
|---|---|---|
| Extruder | 4144 (200 × 4 microsteps × 5.18 gearbox) | 0.1–140 RPM |
| Feeder | 800 | 0.5–180 RPM |

The extruder tops out at 140 RPM because lgpio's software PWM maxes out at
10 kHz. The old maximum (factor 3.0, i.e. 180 RPM) would have needed 12.4 kHz.

Old speed factor → RPM: multiply by 60. For example, 0.20 → 12 RPM and
1.50 → 90 RPM.
