"""Drives the real Tk GUI with simulated GPIO. Skipped without a display."""
import os

import pytest

tk = pytest.importorskip("tkinter")
pytestmark = pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X display")


def overlay(app):
    from wasp.ui.widgets import Overlay
    return [w for w in app.root.winfo_children() if isinstance(w, Overlay)][-1]


def test_profile_workflow(tmp_path):
    from wasp.gpio import SimBackend
    from wasp.motion import Machine
    from wasp.profiles import ProfileStore, Settings
    from wasp.ui.app import App

    m = Machine(SimBackend())
    store, settings = ProfileStore(str(tmp_path)), Settings(str(tmp_path))
    app = App(m, store, settings)
    try:
        app.load_selected()
        assert app.current == "Lab Default" and app.page == "run"

        m.set_ext_rpm(0.4)
        app.poll(schedule=False)
        assert "unsaved" in app.run_modified.label.cget("text")

        app.save_as()
        form = overlay(app)
        for ch in "Slow 3mm":
            form.type(ch)
        form.flip_toggle()            # make default (first letter auto-capitalised)
        form.ok()
        assert store.get("Slow 3mm")["ext_rpm"] == 0.4
        assert store.default_name == "Slow 3mm" and app.current == "Slow 3mm"

        app.save_as()                 # duplicate name is rejected
        form = overlay(app)
        for ch in "slow 3mm":
            form.type(ch)
        form.ok()
        assert "already exists" in form.error.cget("text")
        form.close()

        app.keypad_ext()
        pad = overlay(app)
        for k in "2.5":
            pad.key(k)
        pad.ok()
        assert m.extruder.rpm == 2.5
        app.save_current()
        assert store.get("Slow 3mm")["ext_rpm"] == 2.5

        app.selected = "Lab Default"
        app.delete_selected()
        overlay(app).panel.winfo_children()  # confirm dialog exists
        store.delete("Lab Default")
        app.refresh_profiles()
        assert [p["name"] for p in store.ordered()] == ["Slow 3mm"]

        app.set_theme("light")
        assert settings["theme"] == "light"
        app.show("setup")
        app.poll(schedule=False)
        app.stop_all()
    finally:
        app.root.destroy()
        m.shutdown()
