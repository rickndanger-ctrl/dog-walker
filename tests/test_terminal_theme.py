import configparser
from pathlib import Path
from dog_walker.terminal_theme import sync_omarchy_theme


def fixture_theme(tmp_path, colors=True):
    home = tmp_path / "home"
    source = home / ".local/state/omarchy/current/theme/ghostty.conf"
    source.parent.mkdir(parents=True)
    text = "background = #121212\nforeground = #bebebe\n"
    if colors:
        text += "\n".join(f"palette = {i}=#{i+16:02x}4060" for i in range(16))
    source.write_text(text)
    config = home / ".config/ghostty/config"
    config.parent.mkdir(parents=True)
    config.write_text('font-family = "JetBrainsMono Nerd Font"\nfont-size = 9\n')
    target = tmp_path / "schemes"
    target.mkdir()
    return home, source, target


def test_imports_native_background_font_and_all_standard_ansi_colors_without_changing_source(tmp_path):
    home, source, target = fixture_theme(tmp_path)
    original = source.read_bytes()
    metadata = source.stat().st_mtime_ns
    result = sync_omarchy_theme(home, target)
    scheme = configparser.ConfigParser()
    scheme.read(target / (result["terminal_scheme"] + ".colorscheme"))
    assert scheme["Background"]["Color"] == "18,18,18"
    assert scheme["Foreground"]["Color"] == "190,190,190"
    for index in range(8):
        assert scheme[f"Color{index}"]["Color"] == f"{index + 16},64,96"
        assert scheme[f"Color{index}Intense"]["Color"] == f"{index + 24},64,96"
    assert result["terminal_font"] == "JetBrainsMono Nerd Font" and result["terminal_font_size"] == 9
    assert source.read_bytes() == original and source.stat().st_mtime_ns == metadata
    destination = next(target.iterdir())
    previous = destination.stat().st_mtime_ns
    assert sync_omarchy_theme(home, target) == result
    assert destination.stat().st_mtime_ns == previous


def test_new_native_colors_get_new_scheme_name_so_running_terminals_can_refresh(tmp_path):
    home, source, target = fixture_theme(tmp_path)
    first = sync_omarchy_theme(home, target)
    source.write_text(source.read_text().replace("#121212", "#ffffff"))
    second = sync_omarchy_theme(home, target)
    assert first["terminal_scheme"] != second["terminal_scheme"]
    assert second["terminal_background"] == "#ffffff"
    assert len(list(target.glob("*.colorscheme"))) == 2


def test_missing_or_incomplete_native_theme_keeps_fallback_without_creating_a_partial_scheme(tmp_path):
    home, source, target = fixture_theme(tmp_path, colors=False)
    assert sync_omarchy_theme(home, target) == {}
    assert not list(target.iterdir())
    source.unlink()
    assert sync_omarchy_theme(home, target) == {}
