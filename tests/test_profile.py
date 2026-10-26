import pytest

from take_check.profile import list_profiles, load_profile


def test_standard_profile_loads():
    p = load_profile()
    assert p.name == "Standard" and p.timing.tolerance_ms == 30 and p.palm_mute.root_only is True
    assert {"id": "standard", "name": "Standard"}.items() <= list_profiles()[0].items()


def test_profile_inherits_and_validates(tmp_path):
    (tmp_path / "standard.toml").write_text('name = "Standard"\n[timing]\ntolerance_ms = 30\n')
    (tmp_path / "lead.toml").write_text('name = "Lead"\n[timing]\ntolerance_ms = 45\n[bends]\ntolerance_cents = 40\n')
    p = load_profile("lead", tmp_path)
    assert p.name == "Lead" and p.timing.tolerance_ms == 45 and p.bends.tolerance_cents == 40
    assert p.timing.groove_window_bars == 1.0  # geerbter Code-Standard
    (tmp_path / "bad.toml").write_text("[timing]\ntoleranz = 1\n")
    with pytest.raises(ValueError, match="unbekannter Eintrag"):
        load_profile("bad", tmp_path)
    with pytest.raises(ValueError, match="nicht gefunden"):
        load_profile("gibtsnicht", tmp_path)
    with pytest.raises(ValueError, match="Ungültiger"):
        load_profile("../etc", tmp_path)
