import time

import pytest

from wasp import config as C
from wasp.gpio import SimBackend
from wasp.motion import Extruder, Feeder, Machine, rpm_to_hz


@pytest.fixture
def rig():
    gpio = SimBackend()
    m = Machine(gpio)
    m.extruder.set_prime(0.1)
    m.extruder.set_retract(0.1)
    m.start()
    yield m, gpio
    m.shutdown()


def wait_for(pred, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_rpm_conversion_matches_old_factor():
    # old speed factor 0.20 rev/s == 12 RPM -> same pulse rate as before
    assert rpm_to_hz(12, C.EXT_STEPS_PER_OUTPUT_REV) == pytest.approx(0.20 * C.EXT_STEPS_PER_OUTPUT_REV)


def test_extruder_goes_below_old_minimum(rig):
    m, gpio = rig
    m.set_ext_rpm(0.3)
    assert m.extruder.rpm == 0.3
    m.set_ext_rpm(0)
    assert m.extruder.rpm == C.EXT_MIN_RPM
    m.set_ext_rpm(500)
    assert rpm_to_hz(m.extruder.rpm, C.EXT_STEPS_PER_OUTPUT_REV) <= C.MAX_STEP_HZ


def test_omnicore_cycle_prime_extrude_retract(rig):
    m, gpio = rig
    gpio.write(C.EXT_SIGNAL_PIN, 1)
    assert wait_for(lambda: m.extruder.state == Extruder.EXTRUDING)
    assert gpio.pwm_hz[C.EXT_STEP_PIN] == pytest.approx(rpm_to_hz(12, C.EXT_STEPS_PER_OUTPUT_REV))
    gpio.write(C.EXT_SIGNAL_PIN, 0)
    assert wait_for(lambda: m.extruder.state == Extruder.STOPPED)
    assert gpio.pwm_hz[C.EXT_STEP_PIN] == 0


def test_linked_feeder_follows_extruder(rig):
    m, gpio = rig
    m.feeder.set_linked(True)
    assert gpio.levels[C.FEED_RELAY_PIN] == 1
    gpio.write(C.EXT_SIGNAL_PIN, 1)
    assert wait_for(lambda: m.feeder.state == Feeder.FEEDING)
    gpio.write(C.EXT_SIGNAL_PIN, 0)
    assert wait_for(lambda: m.feeder.state == Feeder.PI_CONTROL)


def test_stop_all_holds_while_robot_signal_high(rig):
    m, gpio = rig
    m.feeder.set_linked(True)
    gpio.write(C.EXT_SIGNAL_PIN, 1)
    assert wait_for(lambda: m.feeder.state == Feeder.FEEDING)
    m.stop_all()
    assert wait_for(lambda: m.extruder.state == Extruder.STOPPED)
    time.sleep(0.2)
    assert m.extruder.state == Extruder.STOPPED          # override stop holds
    assert not m.feeder.feeding and not m.feeder.linked
    assert gpio.levels[C.FEED_RELAY_PIN] == 1            # front panel can't restart it
    gpio.write(C.EXT_SIGNAL_PIN, 0)
    assert wait_for(lambda: not m.extruder.override_stop)


def test_stop_all_during_prime_aborts(rig):
    m, gpio = rig
    m.extruder.set_prime(1.5)
    gpio.write(C.EXT_SIGNAL_PIN, 1)
    assert wait_for(lambda: m.extruder.state == Extruder.PRIMING)
    m.stop_all()
    assert wait_for(lambda: m.extruder.state == Extruder.STOPPED, timeout=0.5)


def test_ratio_lock_tracks_changes(rig):
    m, _ = rig
    m.feeder.set_rpm(54)
    m.set_ext_rpm(4.5)
    m.feeder.set_ratio(7.5)
    m.feeder.set_ratio_lock(True)
    m.set_ext_rpm(4.7)
    assert m.feeder.rpm == pytest.approx(55.5)
    m.feeder.set_rpm(60)            # manual change becomes the new baseline
    m.set_ext_rpm(4.8)
    assert m.feeder.rpm == pytest.approx(60.8)


def test_apply_profile_and_snapshot(rig):
    m, _ = rig
    p = dict(C.DEFAULT_PROFILE, ext_rpm=2.4, feed_rpm=30, ratio=5, link=True, ratio_lock=True)
    m.apply_profile(p)
    snap = m.snapshot()
    assert snap["ext_rpm"] == 2.4 and snap["feed_rpm"] == 30 and snap["link"] and snap["ratio_lock"]
    m.apply_profile(dict(p, link=False), links=False)
    assert m.feeder.linked                               # links=False leaves them alone
