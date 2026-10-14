# Pendant dashboard and robot-speed extrusion: findings and recommendations

*October 13, 2026. A proposal for discussion. Nothing here is built yet.*

## Background

Two projects are converging:

- **GKL_Wasp** (this repo): the Raspberry Pi 5 touchscreen app that drives
  the WASP clay extruder (auger) and the continuous feeder (pump).
- **clay-print-control** (separate, not in this repo): the robot side. It
  covers Grasshopper toolpath export, the RAPID program that loads layers
  one at a time on the ABB OmniCore, and a planned FlexPendant app.

The goal is a **dashboard on the ABB FlexPendant** that shows the print live:
layer, robot speed, position, and extruder state. The extruder should also
**follow the robot's real TCP speed**, so the bead stays even in corners and
when the speed is overridden. Later the same setup should support other
extruders, starting with a **plastic pellet extruder**.

This document records what the current GKL_Wasp code tells us, the main
design decision, and a suggested order of work.

---

## 1. What the current Pi code does today

The clay-print-control README has a list of open questions about the Pi.
The GKL_Wasp code answers most of them:

| Question | Answer from the code |
|---|---|
| How does the Pi talk to the controller? | **One wired digital input.** GPIO17 reads the robot's `Wasp_1_Extruder` output (`wasp/config.py`, `EXT_SIGNAL_PIN`). There is no network link. The Pi's Wi-Fi is only used for update checks. |
| Does it stop both the pump and the auger when the signal drops? | The auger always stops and retracts for `retract_s`. The feeder stops **only if LINK is on** (`Feeder.control_loop` in `wasp/motion.py`). With LINK off, the pump keeps running when the robot stops extruding. |
| Can it read a speed signal? | No. The auger runs at a fixed RPM while the signal is high. |
| Does it report anything back to the controller? | No. Status is only shown on the Pi's own screen. |
| Does it ever write to the controller? | No. That's good: it can't compete with the pendant for write access ("mastership"). |

**Already useful:** RATIO LOCK (`Feeder.follow_extruder`) makes the feeder
follow changes in auger RPM. If the auger starts following robot speed, the
feeder can follow the auger with code that already exists.

**Please confirm:** how GPIO17 is wired to the controller's 24 V output
(optocoupler, relay, or level shifter). This should be written down before
anyone adds more signals.

---

## 2. The main design decision

There are two separate jobs, and they need different paths.

| | Speed-matched flow | Dashboard |
|---|---|---|
| What it does | TCP speed reaches the Pi and sets auger RPM | Shows layer, speed, position, RPMs; later pause and speed override |
| Needs | Reliable, fairly fast, works with nobody looking | A few updates per second; can drop out without harming the print |
| Lives in | A direct robot → Pi link | The FlexPendant app |

**Recommendation: the pendant app must never sit between the robot and the
extruder.** It's a web page running on the pendant that talks to Robot Web
Services (RWS). It's fine for display and for occasional commands, not for a
control loop. The robot → Pi link is the real architecture question; the
dashboard is built on top of it.

```
                 ┌───────────────────────────┐
                 │  OmniCore controller      │
                 │  RAPID: layer, pause,     │
                 │  speed override           │
                 │  TCP speed signal         │
                 └──────┬──────────────┬─────┘
        RWS (read/write)│              │ speed + on/off (see section 3)
                        │              │
              ┌─────────▼───┐    ┌─────▼──────────────────┐
              │ FlexPendant │    │ Raspberry Pi           │
              │ dashboard   │◄───┤ auger + feeder control │
              │ (App SDK)   │ (?)│ (GKL_Wasp)             │
              └─────────────┘    └────────────────────────┘
                 extruder status path: see section 4
```

---

## 3. Getting robot speed to the Pi

| Option | How | Pros | Cons |
|---|---|---|---|
| **A. Pi reads RWS** | Configure the controller's TCP speed system output on a virtual analog signal. The Pi subscribes to it over RWS (websocket) on wired Ethernet. | No new hardware, no extra RobotWare options. The Pi only reads, so no mastership conflict. Can be tried on a virtual controller. | Latency is probably 50–200 ms (to be measured). Depends on the network. Wi-Fi is not good enough. |
| **B. Analog wire** | A physical analog output (0–10 V) on the controller goes to an isolated ADC on the Pi. ABB's `TriggSpeed` instruction is designed for dispensing and can set the output ahead of time to make up for lag. | Deterministic. The standard industrial approach for dispensing. Lag compensation could matter a lot for clay. | Needs an analog I/O module on the OmniCore and an ADC HAT on the Pi. Electrical noise. Still one-way only. |
| **C. Fieldbus** | The Pi acts as an EtherNet/IP (or PROFINET/Modbus) device and exchanges a handful of values with the controller in both directions. | One channel for speed, on/off, layer, and Pi status. Fits the pellet extruder later, since many industrial extruders and drives use these protocols. | Paid RobotWare option. More setup. |

**Recommendation: start with A.** Clay responds to auger changes over
seconds (compressibility, slip in the auger), so 100–200 ms of network
latency is probably not the limiting factor. A is free to try.

- If tests show that *reacting* to speed is too late in corners, move to
  **B** and use `TriggSpeed`'s lag compensation.
- If we also want a clean two-way data path, move to **C**.

Still to check: whether `TriggSpeed` and a fieldbus option are available on
our RobotWare version and robot, and whether the TCP speed output reflects
the live speed override.

### How the Pi would use the speed

A new "robot speed" mode in GKL_Wasp, roughly:

```
auger_rpm = profile_rpm × clamp(tcp_speed / programmed_speed, floor, max)
```

- `programmed_speed` already exists on the controller as `nSpeedProg`.
- `floor` keeps a minimum flow at very low speeds so the bead doesn't break
  in tight corners.
- The result is clamped to the extruder's 0.1–140 RPM range
  (`wasp/config.py`).
- The feeder follows through RATIO LOCK, as it does now.

---

## 4. Getting Pi status onto the pendant

The dashboard should show auger RPM, feeder RPM, extruder state, and whether
STOP ALL is active. There are three possible paths:

1. **The pendant app reads from the Pi directly.** The Pi serves a small
   JSON or websocket status endpoint. This is the simplest, but it's **not
   known whether a pendant app can reach a host outside the controller**,
   given the network layout and the browser's content rules. **This is the
   first thing to test.**
2. **The Pi writes its status into the controller** (signals or PERS
   variables over RWS). This may run into mastership and auto-mode rules,
   and it breaks the "Pi only reads" rule we want to keep.
3. **Fieldbus (option C above).** Status comes back through the
   controller as part of the same exchange.

---

## 5. Supporting other extruders

To add a pellet extruder without rewriting everything, keep the robot side
**extruder-neutral**:

- **The robot publishes process data only:** extruder on/off, TCP speed,
  programmed speed, layer, and possibly bead width and layer height from
  Grasshopper. It never sends RPM.
- **Each extruder driver turns that into its own commands.** Clay: auger RPM
  plus feeder via ratio lock. Pellet: screw RPM. Calibration lives in each
  extruder's profile, as GKL_Wasp profiles already do.
- **Every extruder reports a common status:** ready, running, actual rate,
  fault. Each type adds its own fields. A pellet extruder would add zone
  temperatures, melt pressure, and heaters-at-temperature.
- **The dashboard is driven by config.** A small description per extruder
  type lists which tiles to show. A new extruder means a new description,
  not new UI code.
- **Pellet extruders need a ready interlock.** RAPID should wait
  (`WaitDI`) for "extruder ready" (barrel at temperature) before printing,
  and the dashboard should show it. Clay doesn't need it, but the shared
  interface should leave room for it from the start.

The "shared interface" table in the clay-print-control README should become
a single contract file that the RAPID program, the pendant app, and every
extruder driver are checked against.

---

## 6. Problems found while reading the code

1. **Resume overlaps prime.** The draft pause module (`PrintControlMod` in
   clay-print-control) sets `Wasp_1_Extruder` and immediately calls
   `StartMove` on resume. The Pi is still priming for `prime_s` while the
   robot is already moving, so each resume would likely leave a thin spot.
   Either the robot waits for prime to finish, or the Pi skips prime on a
   resume.
2. **The pump keeps running on pause unless LINK is on.** In robot mode,
   LINK should probably be forced on.
3. **The robot doesn't know when the Pi stops extruding.** If someone
   presses STOP ALL on the Pi, the robot keeps printing with no flow. An
   "extruder stopped / fault" signal back to the robot would let RAPID
   pause. This is about print quality, not safety; safety stops stay
   hardwired.
4. **Two screens could edit the same settings.** If both the pendant and the
   Pi can change RPMs and profiles, one has to be authoritative.
   Recommendation: profiles stay on the Pi. The pendant only displays them
   at first, and maybe selects a profile later.
5. **The Pi is on Wi-Fi.** The speed link needs wired Ethernet on the
   controller's network.

---

## 7. Pendant app: AppStudio or App SDK

ABB has two separate products:

- **AppStudio:** a no-code, drag-and-drop builder.
- **OmniCore App SDK:** HTML/CSS/JavaScript web apps.

**Recommendation: OmniCore App SDK.** The app lives in Git, the
config-driven tiles in section 5 are much easier in code, and it fits how we
already work. AppStudio is fine for a quick throwaway prototype.

Either way, develop against a **virtual controller in RobotStudio** first.

---

## 8. Suggested order of work

1. **Feasibility tests** (virtual controller first, then the real one):
   - Configure the TCP speed system output on a virtual analog signal.
   - Measure how fast RWS subscription updates arrive at a laptop and at
     the Pi.
   - Check whether a pendant app can reach the Pi's IP address.
2. **Read-only dashboard:** layer, TCP speed trace, position, joints.
   Controller data only, no writes.
3. **Robot speed mode on the Pi** (option A). Test it with the Pi's own
   screen showing target vs. actual RPM before involving the pendant.
4. **Pi status on the dashboard**, using whichever path step 1 showed
   works.
5. **Controls:** pause and speed override (these are writes, so mastership
   applies), plus the resume/prime fix from section 6.
6. **The shared extruder contract**, then a pellet extruder driver.

---

## 9. Open questions

- Which robot and **exact RobotWare version**? (The GKL_Wasp README says
  GoFa on OmniCore.)
- Does the controller have **analog I/O**, or an **EtherNet/IP or PROFINET**
  option?
- Can the Pi be put on **wired Ethernet** on the controller's network?
- How is GPIO17 wired to the 24 V robot output?
- Which **pellet extruder**? Does it have its own controller and protocol,
  or would a Pi drive its motors and heaters too?
- Should the pendant **only monitor** at first, or are pause and speed
  override needed from day one?
- Keep GKL_Wasp (extruder side) and clay-print-control (robot and pendant
  side) as **separate repos**, or combine them around the shared contract?
