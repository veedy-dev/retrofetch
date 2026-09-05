from __future__ import annotations

from typing import Any

import pytest
from curl_cffi.requests import Response

from retrofetch.sources import SourceUnavailable
from retrofetch.sources.romsim import RomsimSource


class FixtureRomsim(RomsimSource):
    def __init__(
        self, pages: dict[str, str | Response], shortname: str = "switch"
    ) -> None:
        super().__init__({"shortname": shortname})
        self.pages = pages
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _request(self, method: str, url: str, **kwargs: Any) -> Response:
        assert method == "GET"
        self.calls.append((url, kwargs))
        result = self.pages[
            url
        ]  # Unlisted URLs, including payloads, must never be requested.
        if isinstance(result, Response):
            headers = kwargs.get("headers", {})
            page = (
                url.split("/download?", 1)[0]
                if "HX-Redirect" in result.headers
                else url.split("?", 1)[0]
            )
            valid = (
                kwargs.get("follow_redirects") is False
                and headers.get("Referer") == page
            )
            if "HX-Redirect" in result.headers:
                valid = (
                    valid
                    and headers.get("HX-Request") == "true"
                    and headers.get("HX-Current-URL") == page
                )
            if not valid:
                denied = Response()
                denied.status_code = 403
                return denied
            return result
        response = Response()
        response.status_code = 200
        response.content = result.encode()
        response.url = url
        return response


def redirect(status: int, header: str, url: str) -> Response:
    response = Response()
    response.status_code = status
    response.headers[header] = url
    return response


def post(title: str, href: str = "demo/", kind: str = "post") -> str:
    return f'<h2 class="{kind}-title"><a href="{href}">{title}</a></h2>'


def next_page(href: str) -> str:
    return f'<div class="pages-nav"><div class="the-next-page"><a href="{href}">Next</a></div></div>'


def detail(*mirrors: str) -> str:
    buttons = "".join(
        f'<a class="shortc-button" href="{url}">Mirror</a>' for url in mirrors
    )
    return (
        "<h1>Moon Garden Switch NSP + Update(eShop)</h1>"
        '<div class="entry-content"><h4>Download Links</h4>'
        "<p><strong>BASE GAME(v1.0) [3.32GB]</strong>" + buttons + "</p>"
        '<p><strong>UPDATE(v2)</strong><a class="shortc-button" href="https://bzzhr.to/update">Update</a></p>'
        '<p><strong>DLC</strong><a class="shortc-button" href="https://bzzhr.to/dlc">DLC</a></p>'
        '<p><a class="shortc-button" href="https://evil.example/howto">How to</a></p></div>'
    )


def test_catalog_complete_paging_dedup_cycle_and_limit() -> None:
    source = FixtureRomsim(
        {
            "https://romsim.net/top-games/": post(
                "Moon Garden Switch NSP + Update(eShop)"
            )
            + next_page("page/2/"),
            "https://romsim.net/top-games/page/2/": post("Moon Garden Switch NSP")
            + post("Moon Garden 2 Switch NSP", "sequel/")
            + next_page("page/3/"),
            "https://romsim.net/top-games/page/3/": post(
                "Star Workshop Switch NSP", "star/"
            )
            + next_page("page/2/"),
        }
    )
    assert source.list_popular(0) == ["Moon Garden", "Moon Garden 2", "Star Workshop"]
    assert len(source.calls) == 3
    source.calls.clear()
    assert source.list_popular(1) == ["Moon Garden"]
    assert len(source.calls) == 1


def test_exact_search_base_only_and_buzzheavier_token_redirect() -> None:
    file_page = "https://bzzhr.to/demo123"
    endpoint = file_page + "/download?t=fixture-token"
    direct = "https://ts.bzzhr.to/d/demo123?v=fixture-token"
    source = FixtureRomsim(
        {
            "https://romsim.net/?s=Moon+Garden": post(
                "Moon Garden 2 Switch NSP", "sequel/", "thumb"
            )
            + post("Moon Garden Switch NSP + Update(eShop)", kind="thumb")
            + '<h3><a href="other/">Moon Garden</a></h3>',
            "https://romsim.net/demo/": detail("https://gofile.io/d/demo", file_page),
            file_page: '<title>Moon-Garden-BASE-NSP-Romsim.rar</title><a class="download-btn" hx-get="/demo123/download?t=fixture-token">Download</a>',
            endpoint: redirect(204, "HX-Redirect", direct),
        }
    )
    candidate = source.find_url_for_game("Moon Garden")
    assert candidate is not None
    assert (candidate.url, candidate.filename, candidate.expected_size) == (
        direct,
        "Moon-Garden-BASE-NSP-Romsim.rar",
        None,
    )


def test_legacy_buzzheavier_falls_back_to_buffdrive_without_payload_fetch() -> None:
    page = "https://buffdrive.com/358"
    endpoint = page + "?pt=fixture-token"
    direct = "https://fs8.buffdrive.xyz/fixture/Moon-Garden.rar"
    source = FixtureRomsim(
        {
            "https://romsim.net/?s=Moon+Garden": post(
                "Moon Garden Switch NSP", kind="thumb"
            ),
            "https://romsim.net/demo/": detail("https://bzzhr.to/f/legacy=", page),
            page: "<title>Moon-Garden-BASE-NSP-Romsim.com.rar - BUFFDRIVE</title><button onclick=\"window.location = 'https://buffdrive.com/358?pt=fixture-token'; return false;\">Download</button>",
            endpoint: redirect(302, "Location", direct),
        }
    )
    candidate = source.find_url_for_game("Moon Garden")
    assert candidate is not None and candidate.url == direct
    assert candidate.filename == "Moon-Garden-BASE-NSP-Romsim.com.rar"


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/page/2/",
        "https://romsim.net.evil.example/page/2/",
        "/top-games/not-pagination/",
    ],
)
def test_offsite_or_malformed_pagination_rejected_before_request(target: str) -> None:
    source = FixtureRomsim(
        {"https://romsim.net/top-games/": post("Moon Garden") + next_page(target)}
    )
    with pytest.raises(SourceUnavailable):
        source.list_popular(0)
    assert len(source.calls) == 1


@pytest.mark.parametrize(
    "filename",
    ["Moon-Garden-UPDATE.rar", "Moon-Garden.part1.rar", "../Moon-Garden.rar"],
)
def test_invalid_filename_never_becomes_candidate(filename: str) -> None:
    source = FixtureRomsim(
        {
            "https://bzzhr.to/demo": f'<title>{filename}</title><a class="download-btn" hx-get="/demo/download?t=test">Get</a>',
            "https://bzzhr.to/demo/download?t=test": redirect(
                204, "HX-Redirect", "https://ts.bzzhr.to/d/demo?v=test"
            ),
        }
    )
    with pytest.raises(SourceUnavailable):
        source._buzzheavier(
            "https://bzzhr.to/demo", "https://romsim.net/demo/", "Moon Garden"
        )


@pytest.mark.parametrize(
    "direct",
    [
        "https://evil.example/file.rar",
        "http://ts.bzzhr.to/file.rar",
        "https://bzzhr.to.evil.example/file.rar",
    ],
)
def test_malicious_direct_redirect_is_not_followed(direct: str) -> None:
    source = FixtureRomsim(
        {
            "https://bzzhr.to/demo": '<title>Moon-Garden-BASE.rar</title><a class="download-btn" hx-get="/demo/download?t=test">Get</a>',
            "https://bzzhr.to/demo/download?t=test": redirect(
                204, "HX-Redirect", direct
            ),
        }
    )
    with pytest.raises(SourceUnavailable):
        source._buzzheavier(
            "https://bzzhr.to/demo", "https://romsim.net/demo/", "Moon Garden"
        )
    assert len(source.calls) == 2


def test_challenge_unsupported_host_ambiguous_base_and_inactive_console() -> None:
    source = FixtureRomsim(
        {
            "https://bzzhr.to/demo": '<title>Moon-Garden-BASE.rar</title><a class="download-btn" hx-get="/demo/download?t=test">Get</a>',
            "https://bzzhr.to/demo/download?t=test": "<html>Interactive challenge</html>",
            "https://romsim.net/gofile/": detail("https://gofile.io/d/demo"),
            "https://romsim.net/ambiguous/": detail(
                "https://bzzhr.to/one", "https://bzzhr.to/two"
            ),
            "https://romsim.net/external/": detail("https://evil.example/demo"),
        }
    )
    with pytest.raises(SourceUnavailable, match="challenge"):
        source._buzzheavier(
            "https://bzzhr.to/demo", "https://romsim.net/demo/", "Moon Garden"
        )
    with pytest.raises(SourceUnavailable, match="GoFile"):
        source._resolve_game("https://romsim.net/gofile/", "Moon Garden")
    with pytest.raises(SourceUnavailable, match="ambiguous"):
        source._resolve_game("https://romsim.net/ambiguous/", "Moon Garden")
    with pytest.raises(SourceUnavailable):
        source._resolve_game("https://romsim.net/external/", "Moon Garden")
    inactive = FixtureRomsim({}, shortname="nes")
    assert inactive.list_popular(0) == []
    assert inactive.find_url_for_game("Moon Garden") is None
    assert inactive.calls == []


def test_demo_and_sequel_are_not_full_game_and_no_progress_stops() -> None:
    source = FixtureRomsim(
        {
            "https://romsim.net/?s=Moon+Garden": post(
                "Moon Garden Switch NSP Demo", kind="thumb"
            )
            + post("Moon Garden 2 Switch NSP", kind="thumb"),
            "https://romsim.net/top-games/": post("Moon Garden Switch NSP")
            + next_page("page/2/"),
            "https://romsim.net/top-games/page/2/": post("Moon Garden Switch NSP")
            + next_page("page/3/"),
        }
    )
    assert source.find_url_for_game("Moon Garden") is None
    assert source.list_popular(0) == ["Moon Garden"]
    assert len(source.calls) == 3


def test_wrong_detail_and_wrong_host_file_never_resolve() -> None:
    source = FixtureRomsim(
        {
            "https://romsim.net/?s=Moon+Garden": post(
                "Moon Garden Switch NSP", kind="thumb"
            ),
            "https://romsim.net/demo/": detail("https://bzzhr.to/other").replace(
                "<h1>Moon Garden ", "<h1>Moon Garden 2 "
            ),
            "https://bzzhr.to/other": '<title>Moon-Garden-2-BASE-NSP-Romsim.rar</title><a class="download-btn" hx-get="/other/download?t=test">Get</a>',
            "https://buffdrive.com/358": '<title>Moon-Garden-2-BASE-NSP-Romsim.com.rar - BUFFDRIVE</title><button onclick="window.location = &quot;https://buffdrive.com/358?pt=test&quot;; return false;">Get</button>',
        }
    )
    with pytest.raises(SourceUnavailable, match="detail title"):
        source.find_url_for_game("Moon Garden")
    with pytest.raises(SourceUnavailable, match="host file"):
        source._buzzheavier(
            "https://bzzhr.to/other", "https://romsim.net/demo/", "Moon Garden"
        )
    with pytest.raises(SourceUnavailable, match="host file"):
        source._buffdrive(
            "https://buffdrive.com/358", "https://romsim.net/demo/", "Moon Garden"
        )
