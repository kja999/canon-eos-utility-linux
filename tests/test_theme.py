from PySide6.QtGui import QColor

from canon_eos_utility.ui import theme


def test_parse_color_hex_and_rgb():
    assert theme._parse_color("#9141ac").name() == "#9141ac"
    assert theme._parse_color("rgb(145, 65, 172)").name() == "#9141ac"
    assert theme._parse_color("rgba(145, 65, 172, 1.0)").name() == "#9141ac"


def test_resolve_gtk_define_follows_indirection():
    defines = {
        "theme_selected_bg_color": "@purple",
        "purple": "#9141ac",
    }
    assert theme._resolve_gtk_define(defines, "theme_selected_bg_color").name() == "#9141ac"


def test_parse_gtk_defines(tmp_path):
    css = tmp_path / "gtk.css"
    css.write_text(
        "@define-color purple #9141ac;\n@define-color theme_selected_bg_color @purple;\n"
    )
    defines = theme._parse_gtk_defines(str(css))
    assert defines["purple"] == "#9141ac"
    assert defines["theme_selected_bg_color"] == "@purple"


def test_resolve_accent_explicit_colour():
    theme.resolve_accent(None, "#9141ac")
    assert theme.ACCENT == "#9141ac"
    assert theme.ON_ACCENT == "#ffffff"  # dark colour -> light text
    # A light colour gets dark text.
    theme.resolve_accent(None, "#eeeeee")
    assert theme.ON_ACCENT == "#1a1a1a"
    # Reset to the default so other tests are unaffected.
    theme.set_accent(QColor(theme.DEFAULT_ACCENT))


def test_parse_portal_accent():
    # gdbus output for GNOME's orange accent.
    orange = "(<<(0.92941176891326904, 0.35686275362968445, 0.0)>>,)"
    assert theme._parse_portal_accent(orange).name() == "#ed5b00"
    blue = "(<<(0.20784313976764679, 0.51764708757400513, 0.89411765336990356)>>,)"
    assert theme._parse_portal_accent(blue).name() == "#3584e4"
    # Unsupported key: the portal answers (0, 0, 0) or an error payload.
    assert theme._parse_portal_accent("(<<(0.0, 0.0, 0.0)>>,)") is None
    assert theme._parse_portal_accent("()") is None


def test_portal_accent_wins_over_gsettings(monkeypatch):
    """In a sandbox gsettings cannot reach dconf; the portal must be used."""
    monkeypatch.setattr(theme, "_platform_highlight", lambda app: None)
    monkeypatch.setattr(theme, "_gsettings_get", lambda key: None)
    monkeypatch.setattr(theme, "_gtk_theme_color", lambda: None)
    monkeypatch.setattr(
        theme,
        "_portal_accent",
        lambda: QColor("#ed5b00"),
    )
    try:
        color = theme.resolve_accent(None)
        assert color.name() == "#ed5b00"
        assert theme.ACCENT == "#ed5b00"
        assert theme.ON_ACCENT == "#ffffff"
    finally:
        theme.set_accent(QColor(theme.DEFAULT_ACCENT))
