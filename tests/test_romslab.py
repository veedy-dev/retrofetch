from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import urlencode

import pytest
from curl_cffi.requests import Response

from retrofetch.sources import SourceUnavailable
from retrofetch.sources.romslab import RomsLabSource

SITE = "https://romslab.com"
CATEGORY = SITE + "/category/switch-games-1/"
TITLE = "Cobalt Voyage"
FILENAME = "Cobalt_Voyage_SWITCH_NSP_BASE_GAME.rar"
HOST = "https://filekeeper.net/fixture123/" + FILENAME
DIRECT = "https://tunnel1.dlproxy.uk/download/authorized-fixture?sig=synthetic"
SEARCH = SITE + "/?" + urlencode({"s": TITLE, "post_type": "post"})


def _listing(rows: list[tuple[str, str, str]], next_url: str = "") -> str:
    body = '<ul class="grid-posts">'
    for title, href, category in rows:
        body += f'<li class="post-item {category}"><h2><a class="post-title" href="{escape(href)}">{escape(title)}</a></h2></li>'
    body += "</ul>"
    if next_url:
        body += f'<div class="wp-pagenavi"><a class="nextpostslink" href="{escape(next_url)}">Next</a></div>'
    return body


def _detail(links: list[tuple[str, str]], title: str = TITLE) -> str:
    return (
        f'<h1 class="name">{title} Switch NSP Free Download</h1><div class="btns">'
        + "".join(
            f'<a class="btn-download" href="{escape(url)}">{label}</a>'
            for label, url in links
        )
        + "</div>"
    )


def _source(
    monkeypatch: pytest.MonkeyPatch, pages: dict[str, str]
) -> tuple[RomsLabSource, list[str]]:
    source = RomsLabSource({"shortname": "switch"})
    calls: list[str] = []

    def get(url: str) -> str:
        calls.append(url)
        return pages[url]

    monkeypatch.setattr(source, "_get", get)
    return source, calls


def test_category_pagination_limit_dedup_and_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second = CATEGORY + "page/2/"
    first_rows = [(TITLE + " Switch NSP Free Download", "/cobalt/", "")]
    source, calls = _source(
        monkeypatch,
        {
            CATEGORY: _listing(first_rows, second),
            second: _listing(
                first_rows + [("Orchard Quest Switch XCI", "/orchard/", "")], CATEGORY
            ),
        },
    )
    assert source.list_popular(1) == [TITLE]
    assert calls == [CATEGORY]
    calls.clear()
    assert source.list_popular(0) == [TITLE, "Orchard Quest"]
    assert calls == [CATEGORY, second]


@pytest.mark.parametrize(
    "next_url",
    ["https://evil.invalid/page/2/", SITE + "/games-index-1/", CATEGORY + "page/nope/"],
)
def test_category_rejects_offsite_or_malformed_pagination(
    monkeypatch: pytest.MonkeyPatch, next_url: str
) -> None:
    source, calls = _source(
        monkeypatch, {CATEGORY: _listing([(TITLE, "/cobalt/", "")], next_url)}
    )
    with pytest.raises(SourceUnavailable):
        source.list_popular(0)
    assert calls == [CATEGORY]


def test_search_excludes_other_console_sequel_and_demo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, calls = _source(
        monkeypatch,
        {
            SEARCH: _listing(
                [
                    (TITLE, "/ps5/", "category-ps5-games"),
                    (TITLE + " 2 Switch NSP", "/sequel/", "category-switch-games-1"),
                    (TITLE + " Switch NSP Demo", "/demo/", "category-switch-games-1"),
                ]
            )
        },
    )
    assert source.find_url_for_game(TITLE) is None
    assert calls == [SEARCH]


@pytest.mark.parametrize(
    "filename",
    [
        "Cobalt_Voyage_SWITCH_NSP_UPDATE_1.0.rar",
        "Cobalt_Voyage_SWITCH_NSP_DLC.rar",
        "Cobalt_Voyage_SWITCH_NSP_BASE_GAME.part1.rar",
        "Cobalt_Voyage_SWITCH_NSP.rar",
        "Cobalt_Voyage_2_SWITCH_NSP_BASE_GAME.rar",
    ],
)
def test_protected_base_does_not_select_unsafe_mirror(
    monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    source, _ = _source(
        monkeypatch,
        {
            SEARCH: _listing(
                [(TITLE + " Switch NSP", "/cobalt/", "category-switch-games-1")]
            ),
            SITE + "/cobalt/": _detail(
                [
                    ("Download Here", "https://datanodes.to/protected/" + FILENAME),
                    ("Mirror2", "https://filekeeper.net/fixture123/" + filename),
                ]
            ),
        },
    )

    def unexpected(*args: Any, **kwargs: Any) -> Response:
        pytest.fail("Unsafe mirror or protected host must not be requested")

    monkeypatch.setattr(source, "_request", unexpected)
    with pytest.raises(SourceUnavailable, match="Datanodes.*CAPTCHA"):
        source.find_url_for_game(TITLE)


def _form(**changes: str) -> str:
    attrs = {
        "code": "fixture123",
        "countdown": "5",
        "rand": "",
        "referer": "",
        "method": "",
        "has-password": "false",
        "has-captcha": "false",
    }
    attrs.update(changes)
    return (
        '<div id="download-countdown" '
        + " ".join(f'data-{key}="{value}"' for key, value in attrs.items())
        + "></div>"
    )


def _response(url: str, body: str = "", status: int = 200, **headers: str) -> Response:
    class FixtureResponse(Response):
        def iter_content(
            self, chunk_size: int | None = None, decode_unicode: bool = False
        ):
            yield self.content

    response = FixtureResponse()
    response.url = url
    response.status_code = status
    response.headers.update({"Content-Type": "text/html", **headers})
    response.content = body.encode()
    return response


@pytest.mark.parametrize(
    "actual_filename",
    [
        FILENAME.replace("_", " "),
        "Orchard Quest SWITCH NSP BASE GAME.rar",
        "Cobalt Voyage SWITCH NSP UPDATE.rar",
        "Cobalt Voyage SWITCH NSP BASE GAME.part1.rar",
        "../Cobalt Voyage SWITCH NSP BASE GAME.rar",
        "",
    ],
)
def test_filekeeper_session_countdown_and_metadata_redirect(
    monkeypatch: pytest.MonkeyPatch, actual_filename: str
) -> None:
    source, _ = _source(
        monkeypatch,
        {
            SEARCH: _listing(
                [(TITLE + " Switch NSP", "/cobalt/", "category-switch-games-1")]
            ),
            SITE + "/cobalt/": _detail([("Mirror2", HOST + "\n")]),
        },
    )
    waits: list[float] = []
    monkeypatch.setattr("retrofetch.sources.romslab.time.sleep", waits.append)

    class Session:
        cookie = ""

        def request(self, method: str, url: str, **kwargs: Any) -> Response:
            if url == HOST:
                self.cookie = "fixture123"
                return _response(url, status=302, Location="/download")
            if url == "https://filekeeper.net/download":
                if self.cookie != "fixture123":
                    return _response(url, status=403)
                if method == "GET":
                    return _response(url, _form())
                expected = {
                    "op": "download2",
                    "id": "fixture123",
                    "rand": "",
                    "referer": "",
                    "method_free": "Free download",
                    "down_direct": "1",
                }
                if 5 not in waits or kwargs.get("data") != expected:
                    return _response(url, status=403)
                return _response(url, status=302, Location=DIRECT)
            assert (method, url) == ("HEAD", DIRECT), (
                "must never GET payload during resolution"
            )
            response = _response(url)
            response.headers["Content-Length"] = "1024"
            response.headers["Content-Disposition"] = (
                f'attachment; filename="{actual_filename}"'
            )
            return response

    monkeypatch.setattr(
        "retrofetch.sources._switch_archive.Session", lambda **kwargs: Session()
    )
    if actual_filename == FILENAME.replace("_", " "):
        candidate = source.find_url_for_game(TITLE)
        assert candidate is not None
        assert (candidate.url, candidate.filename, candidate.expected_size) == (
            DIRECT,
            FILENAME,
            1024,
        )
    else:
        with pytest.raises(SourceUnavailable):
            source.find_url_for_game(TITLE)


@pytest.mark.parametrize(
    "changes",
    [
        {"has-captcha": "true"},
        {"has-password": "true"},
        {"code": "different"},
        {"countdown": "invalid"},
    ],
)
def test_filekeeper_challenge_or_identity_failure_never_posts(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]
) -> None:
    source = RomsLabSource({"shortname": "switch"})
    calls: list[str] = []

    def request(method: str, url: str, **kwargs: Any) -> Response:
        calls.append(method)
        assert method == "GET"
        return _response("https://filekeeper.net/download", _form(**changes))

    monkeypatch.setattr(source, "_request", request)
    with pytest.raises(SourceUnavailable):
        source._filekeeper(HOST, FILENAME, SITE + "/cobalt/")
    assert calls == ["GET"]


def test_inactive_console_does_not_request(monkeypatch: pytest.MonkeyPatch) -> None:
    source = RomsLabSource({"shortname": "ps5"})

    def unexpected(url: str) -> str:
        pytest.fail("inactive provider must not request metadata")

    monkeypatch.setattr(source, "_get", unexpected)
    assert source.list_popular(0) == []
    assert source.find_url_for_game(TITLE) is None


def test_pagination_stops_on_repeated_posts_without_following_new_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second = CATEGORY + "page/2/"
    rows = [(TITLE, "/cobalt/", "")]
    source, calls = _source(
        monkeypatch,
        {
            CATEGORY: _listing(rows, second),
            second: _listing(rows, CATEGORY + "page/3/"),
        },
    )
    assert source.list_popular(0) == [TITLE]
    assert calls == [CATEGORY, second]


def test_search_paginates_past_other_console_and_rechecks_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second = SITE + "/page/2/?" + urlencode({"s": TITLE, "post_type": "post"})
    source, calls = _source(
        monkeypatch,
        {
            SEARCH: _listing([(TITLE, "/ps5/", "category-ps5-games")], second),
            second: _listing([(TITLE, "/cobalt/", "category-switch-games-1")]),
            SITE + "/cobalt/": _detail([], title=TITLE + " 2"),
        },
    )
    with pytest.raises(SourceUnavailable, match="detail title"):
        source.find_url_for_game(TITLE)
    assert calls == [SEARCH, second, SITE + "/cobalt/"]
