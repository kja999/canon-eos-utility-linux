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
