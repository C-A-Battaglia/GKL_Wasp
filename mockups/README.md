# GUI Concepts (for review, not yet built)

Three design directions for the 800×480 Pi touchscreen. Pick one (or mix parts)
before the Tkinter GUI is rebuilt. All three use only flat colours, solid
rectangles and plain text, so each one can be built in Tkinter.

| File | Concept |
|---|---|
| `concept_a_dark.jpg` | **A · Control Room**: dark, high contrast, large numerals, step-size selector (0.1 / 1 / 10) |
| `concept_b_light.jpg` | **B · CraftLab Refined**: same look as the current build but cleaned up, with coarse + fine nudge buttons |
| `concept_c_sidebar.jpg` | **C · Workstation**: pages on a side rail (Run / Profiles / Setup), always-visible STOP ALL, plus the on-screen keyboard for naming profiles |

All three include:
- **Profile picker on startup**, with the ★ Default pinned at the top.
- **Save / Save As** on the run screen, with a "modified" flag when live values differ from the loaded profile.
- **Speeds in real RPM** instead of the old "speed factor" (see below).

## The speed numbering

In `WASP3326.py` the number on screen is a **speed factor**: revolutions per
second of the output shaft.

- Extruder: steps/s = factor × 200 × 4 microsteps × 5.18 gearbox = factor × 4144.
  So the default `0.20` means 0.2 rev/s, which is **12 RPM** at the auger.
- Feeder: steps/s = factor × 800. So `1.50` means **90 RPM**.
- `MIN_SPEED_FACTOR = 0.10` is why the extruder can't go below 0.1. That is
  6 RPM, and the hardware can go much slower.

Proposed change: show and store **output RPM** on both motors, with a 0.1 RPM
fine step. The extruder minimum drops to about 0.1 RPM (≈7 steps/s), and a small
line under each readout shows rev/s and steps/s for debugging.
