import pytest

from radio_epg.ids import canonical_channel_id, tuple_alias


def test_canonical_channel_id_includes_city() -> None:
    assert canonical_channel_id("kbs", "1radio", "busan") == "kbs.1radio.busan"


def test_canonical_channel_id_uses_main_defaults() -> None:
    assert canonical_channel_id("obs", None, None) == "obs.main.main"


def test_canonical_channel_id_normalizes_ascii_case() -> None:
    assert canonical_channel_id("KBS", "1RADIO", "BUSAN") == "kbs.1radio.busan"


def test_canonical_channel_id_rejects_non_ascii_segments() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        canonical_channel_id("한국방송", None, None)


def test_tuple_alias_distinguishes_missing_values() -> None:
    assert tuple_alias("tbn", None, "busan") == "tbn/main/busan"
