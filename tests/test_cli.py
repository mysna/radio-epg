from radio_epg.cli import app_name, build_parser


def test_app_name() -> None:
    assert app_name() == "radio-epg"


def test_cli_exposes_collection_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["collect", "--all"]).command == "collect"
    assert parser.parse_args(["collect", "--source", "kbs"]).source == "kbs"
    assert parser.parse_args(["validate-fixtures"]).command == "validate-fixtures"
    assert parser.parse_args(["coverage"]).command == "coverage"
