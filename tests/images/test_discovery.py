from radio_epg.images.discovery import (
    discover_html_image,
    discover_wikimedia_image,
    first_discovered_image,
)


def test_wikimedia_metadata_preserves_author_license_and_attribution() -> None:
    payload = {
        "query": {
            "pages": {
                "42": {
                    "imageinfo": [
                        {
                            "url": "https://upload.wikimedia.org/example-logo.png",
                            "descriptionurl": "https://commons.wikimedia.org/wiki/File:Example.png",
                            "extmetadata": {
                                "Artist": {"value": "<b>Example Author</b>"},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "Credit": {"value": "Example attribution"},
                            },
                        }
                    ]
                }
            }
        }
    }

    candidate = discover_wikimedia_image(
        payload,
        entity_type="channel",
        entity_id="kbs.1radio.main",
    )

    assert candidate is not None
    assert candidate.source_url == "https://upload.wikimedia.org/example-logo.png"
    assert candidate.source_page_url.endswith("File:Example.png")
    assert candidate.rights_status == "known"
    assert candidate.author == "Example Author"
    assert candidate.license == "CC BY-SA 4.0"
    assert candidate.attribution == "Example attribution"


def test_namuwiki_og_image_is_a_discovery_candidate_with_unknown_rights() -> None:
    html = '<html><head><meta property="og:image" content="/images/kbs.png"></head></html>'

    candidate = discover_html_image(
        html,
        page_url="https://namu.wiki/w/KBS",
        entity_type="broadcaster",
        entity_id="kbs",
    )

    assert candidate is not None
    assert candidate.source_url == "https://namu.wiki/images/kbs.png"
    assert candidate.rights_status == "unknown"


def test_official_page_is_used_only_when_earlier_discovery_sources_are_empty() -> None:
    official = discover_html_image(
        '<meta property="og:image" content="https://static.kbs.co.kr/logo.png">',
        page_url="https://www.kbs.co.kr/",
        entity_type="broadcaster",
        entity_id="kbs",
    )

    assert first_discovered_image((None, None, official)) == official
