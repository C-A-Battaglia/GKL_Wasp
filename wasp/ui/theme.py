"""Colour palettes and fonts. Switching theme rebuilds the UI from these."""

DARK = {
    "name": "dark",
    "bg": "#121418",          # page background
    "surface": "#1c2027",     # cards / bands
    "inset": "#0c0e11",       # wells inside cards
    "raised": "#2c323b",      # neutral buttons
    "raised_fg": "#ffffff",
    "border": "#2c323b",
    "text": "#f1f3f5",
    "muted": "#9aa1ab",
    "faint": "#5f6670",
    "accent": "#ff7a3d",
    "accent_fg": "#111111",
    "green": "#2ecc71",
    "red": "#e5483b",
    "yellow": "#f5b82e",
    "gray": "#5f6670",
    "rail": "#08090b",
    "rail_fg": "#8e97a3",
    "rail_on": "#ff7a3d",
    "rail_on_fg": "#111111",
    "disabled_bg": "#1f242b",
    "disabled_fg": "#555c66",
    "chip_warn_bg": "#3a2c12",
    "chip_warn_fg": "#f5b82e",
    "green_fg": "#0b0d10",
    "yellow_fg": "#0b0d10",
    "red_fg": "#ffffff",
    "gray_fg": "#ffffff",
}

LIGHT = {
    "name": "light",
    "bg": "#eef1f5",
    "surface": "#ffffff",
    "inset": "#eef1f5",
    "raised": "#dfe4ea",
    "raised_fg": "#18202b",
    "border": "#d0d7e0",
    "text": "#18202b",
    "muted": "#5b6573",
    "faint": "#98a2af",
    "accent": "#e1622f",
    "accent_fg": "#ffffff",
    "green": "#1a9e5f",
    "red": "#d93636",
    "yellow": "#f0a92e",
    "gray": "#7a8696",
    "rail": "#18202b",
    "rail_fg": "#8e9aab",
    "rail_on": "#e1622f",
    "rail_on_fg": "#ffffff",
    "disabled_bg": "#e6eaef",
    "disabled_fg": "#a3acb8",
    "chip_warn_bg": "#fff1d6",
    "chip_warn_fg": "#8a5a00",
    "green_fg": "#ffffff",
    "yellow_fg": "#18202b",
    "red_fg": "#ffffff",
    "gray_fg": "#ffffff",
}

THEMES = {"dark": DARK, "light": LIGHT}

_family = None


def pick_family(root):
    """Prefer Inter if installed, else DejaVu Sans (Pi OS default)."""
    global _family
    import tkinter.font as tkfont
    available = set(tkfont.families(root))
    for fam in ("Inter", "DejaVu Sans", "Liberation Sans", "Helvetica"):
        if fam in available:
            _family = fam
            return fam
    _family = "TkDefaultFont"
    return _family


def font(px, bold=True):
    """Font tuple with size in *pixels* (negative size) so layouts match
    regardless of the display's DPI setting."""
    return (_family or "Helvetica", -int(px), "bold" if bold else "normal")
