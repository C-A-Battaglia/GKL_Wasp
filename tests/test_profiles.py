import json

from wasp.profiles import ProfileStore, Settings, same_settings

SNAP = dict(ext_rpm=4.5, feed_rpm=54, ratio=7.5, retract_s=0.4, prime_s=0.35, link=True, ratio_lock=True)


def test_fresh_store_has_default(tmp_path):
    s = ProfileStore(str(tmp_path))
    assert s.default()["name"] == "Lab Default"
    assert s.default()["ext_rpm"] == 12.0
    assert (tmp_path / "profiles.json").exists()


def test_save_reload_and_order(tmp_path):
    s = ProfileStore(str(tmp_path))
    s.put("Old", SNAP)
    s.get("Old")["last_used"] = 1
    s.put("New", SNAP, nozzle="6 mm")
    s.save()
    s2 = ProfileStore(str(tmp_path))
    names = [p["name"] for p in s2.ordered()]
    assert names == ["Lab Default", "New", "Old"]      # default pinned, then most recent
    assert s2.get("new")["nozzle"] == "6 mm"            # case-insensitive lookup


def test_default_can_change_and_survives_rename(tmp_path):
    s = ProfileStore(str(tmp_path))
    s.put("A", SNAP)
    s.set_default("A")
    assert s.rename("A", "B")
    assert ProfileStore(str(tmp_path)).default()["name"] == "B"


def test_cannot_delete_last_and_delete_default_falls_back(tmp_path):
    s = ProfileStore(str(tmp_path))
    assert not s.delete("Lab Default")
    s.put("A", SNAP)
    assert s.delete("Lab Default")
    assert s.default()["name"] == "A"


def test_rename_refuses_clash(tmp_path):
    s = ProfileStore(str(tmp_path))
    s.put("A", SNAP)
    assert not s.rename("A", "lab default")


def test_values_clamped_and_below_old_minimum(tmp_path):
    s = ProfileStore(str(tmp_path))
    p = s.put("Slow", dict(SNAP, ext_rpm=0.3))
    assert p["ext_rpm"] == 0.3                          # old limit was 6 RPM
    p = s.put("Silly", dict(SNAP, ext_rpm=999, ratio=0))
    assert p["ext_rpm"] == 140.0 and p["ratio"] == 0.5


def test_corrupt_file_is_kept_aside(tmp_path):
    (tmp_path / "profiles.json").write_text("{not json")
    s = ProfileStore(str(tmp_path))
    assert s.default()["name"] == "Lab Default"
    assert (tmp_path / "profiles.json.corrupt").exists()
    json.loads((tmp_path / "profiles.json").read_text())


def test_same_settings():
    assert same_settings(SNAP, dict(SNAP, notes="x"))
    assert not same_settings(SNAP, dict(SNAP, ext_rpm=4.6))


def test_settings_persist(tmp_path):
    Settings(str(tmp_path))["theme"] = "light"
    assert Settings(str(tmp_path))["theme"] == "light"
