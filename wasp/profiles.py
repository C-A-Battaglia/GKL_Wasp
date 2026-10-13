"""
Profile presets and app settings, stored as JSON.

Default location: ~/.wasp_control/  (override with --data-dir)
  profiles.json  - {"default": "<name>", "profiles": [ {...}, ... ]}
  settings.json  - {"theme": "dark"}

Files are written to a temp file and renamed, so a power cut mid-save
can't leave a half-written file.
"""

import json
import os
import time

from . import config as C

PROFILE_FIELDS = ("ext_rpm", "feed_rpm", "ratio", "retract_s", "prime_s", "link", "ratio_lock")
MAX_NAME_LEN = 32


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _read_json(path, fallback):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback
    except (ValueError, OSError):
        # Keep the unreadable file for inspection rather than overwriting it.
        os.replace(path, path + ".corrupt")
        print(f"WARNING: {path} was unreadable; moved to {path}.corrupt")
        return fallback


def normalize(p):
    """Fill in missing fields and coerce types so old/hand-edited files load."""
    out = dict(C.DEFAULT_PROFILE)
    out.update({k: v for k, v in p.items() if k in out or k == "last_used"})
    out["name"] = str(out["name"]).strip()[:MAX_NAME_LEN] or "Unnamed"
    for k in ("ext_rpm", "feed_rpm", "ratio", "retract_s", "prime_s"):
        out[k] = float(out[k])
    out["ext_rpm"] = round(C.clamp(out["ext_rpm"], C.EXT_MIN_RPM, C.EXT_MAX_RPM), 1)
    out["feed_rpm"] = round(C.clamp(out["feed_rpm"], C.FEED_MIN_RPM, C.FEED_MAX_RPM), 1)
    out["ratio"] = round(C.clamp(out["ratio"], C.MIN_RATIO, C.MAX_RATIO), 2)
    out["retract_s"] = round(C.clamp(out["retract_s"], C.MIN_RETRACT_PRIME, C.MAX_RETRACT_PRIME), 2)
    out["prime_s"] = round(C.clamp(out["prime_s"], C.MIN_RETRACT_PRIME, C.MAX_RETRACT_PRIME), 2)
    out["link"] = bool(out["link"])
    out["ratio_lock"] = bool(out["ratio_lock"])
    out["nozzle"] = str(out.get("nozzle", ""))
    out["notes"] = str(out.get("notes", ""))
    out["last_used"] = float(out.get("last_used", 0) or 0)
    return out


def same_settings(a, b):
    """True if two profiles/snapshots have the same machine settings."""
    for k in PROFILE_FIELDS:
        va, vb = a.get(k), b.get(k)
        if isinstance(va, float) or isinstance(vb, float):
            if abs(float(va) - float(vb)) > 1e-6:
                return False
        elif va != vb:
            return False
    return True


class ProfileStore:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.path = os.path.join(data_dir, "profiles.json")
        raw = _read_json(self.path, None)
        if not raw or not raw.get("profiles"):
            raw = {"default": C.DEFAULT_PROFILE["name"], "profiles": [dict(C.DEFAULT_PROFILE)]}
        self.profiles = []
        for p in raw["profiles"]:
            p = normalize(p)
            if not self.get(p["name"]):
                self.profiles.append(p)
        self.default_name = raw.get("default")
        if not self.get(self.default_name):
            self.default_name = self.profiles[0]["name"]
        self.save()

    def save(self):
        _atomic_write(self.path, {"default": self.default_name, "profiles": self.profiles})

    def get(self, name):
        if name is None:
            return None
        key = name.strip().lower()
        for p in self.profiles:
            if p["name"].lower() == key:
                return p
        return None

    def ordered(self):
        """Default first, then most recently used."""
        default = self.get(self.default_name)
        rest = sorted((p for p in self.profiles if p is not default),
                      key=lambda p: (-p["last_used"], p["name"].lower()))
        return [default] + rest

    def default(self):
        return self.get(self.default_name)

    def put(self, name, settings, nozzle=None, notes=None):
        """Create or overwrite a profile with the given machine settings."""
        existing = self.get(name)
        base = dict(existing) if existing else {"name": name}
        base.update({k: settings[k] for k in PROFILE_FIELDS})
        if nozzle is not None:
            base["nozzle"] = nozzle
        if notes is not None:
            base["notes"] = notes
        base["last_used"] = time.time()
        p = normalize(base)
        if existing:
            self.profiles[self.profiles.index(existing)] = p
        else:
            self.profiles.append(p)
        self.save()
        return p

    def touch(self, name):
        p = self.get(name)
        if p:
            p["last_used"] = time.time()
            self.save()

    def rename(self, old, new):
        new = new.strip()[:MAX_NAME_LEN]
        p = self.get(old)
        if not p or not new:
            return False
        clash = self.get(new)
        if clash and clash is not p:
            return False
        was_default = p is self.default()
        p["name"] = new
        if was_default:
            self.default_name = new
        self.save()
        return True

    def duplicate(self, name):
        p = self.get(name)
        if not p:
            return None
        n = 2
        while self.get(f"{p['name'][:MAX_NAME_LEN - 4]} ({n})"):
            n += 1
        copy = dict(p, name=f"{p['name'][:MAX_NAME_LEN - 4]} ({n})", last_used=time.time())
        self.profiles.append(copy)
        self.save()
        return copy

    def delete(self, name):
        p = self.get(name)
        if not p or len(self.profiles) == 1:
            return False
        self.profiles.remove(p)
        if p["name"] == self.default_name:
            self.default_name = self.profiles[0]["name"]
        self.save()
        return True

    def set_default(self, name):
        p = self.get(name)
        if p:
            self.default_name = p["name"]
            self.save()


class Settings:
    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "settings.json")
        self.data = {"theme": "dark"}
        self.data.update(_read_json(self.path, {}))

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value
        _atomic_write(self.path, self.data)
