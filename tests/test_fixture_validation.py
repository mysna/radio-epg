from radio_epg.fixture_validation import validate_fixtures


def test_fixture_validation_checks_kbs_and_five_national_contracts() -> None:
    result = validate_fixtures()

    assert result.mapping_count == 6
    assert result.fixture_family_count == 6
