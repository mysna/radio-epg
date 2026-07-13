from radio_epg.cli import app_name


def test_app_name() -> None:
    assert app_name() == "radio-epg"
