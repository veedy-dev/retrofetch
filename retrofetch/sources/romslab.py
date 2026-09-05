from __future__ import annotations

import re
import time
from collections.abc import Iterator
from email.message import Message
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

from selectolax.parser import HTMLParser

from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._switch_archive import (
    SwitchArchiveSource,
    candidate_for,
    checked_url,
    clean_title,
    title_key,
)

_CATEGORY = "/category/switch-games-1/"
_POSTS = ".grid-posts > li.post-item"


class RomsLabSource(SwitchArchiveSource):
    name = "romslab"
    base_url = "https://romslab.com"
    allowed_hosts = ("romslab.com", "filekeeper.net", "dlproxy.uk", "datanodes.to")

    def _site_url(self, value: str, current: str) -> str:
        url = checked_url(
            urljoin(current, value.strip()), (urlsplit(self.base_url).hostname or "",)
        )
        if urlsplit(url).hostname != urlsplit(self.base_url).hostname:
            raise SourceUnavailable("RomsLab returned an offsite catalog link")
        return url

    def _entries(self, search: str | None = None) -> Iterator[tuple[str, str]]:
        url = urljoin(
            self.base_url,
            _CATEGORY
            if search is None
            else "/?" + urlencode({"s": search, "post_type": "post"}),
        )
        pages: set[str] = set()
        posts: set[str] = set()
        while url not in pages:
            pages.add(url)
            tree = HTMLParser(self._get(url))
            selector = _POSTS + (
                ".category-switch-games-1" if search is not None else ""
            )
            progress = False
            # Search pages may contain only other consoles; count all posts for progress.
            for post in tree.css(_POSTS + " h2 a.post-title"):
                href = post.attributes.get("href", "")
                if not href:
                    continue
                page = self._site_url(href, url)
                if page not in posts:
                    posts.add(page)
                    progress = True
            for link in tree.css(selector + " h2 a.post-title"):
                href = link.attributes.get("href", "")
                raw_title = link.text(strip=True)
                title = clean_title(raw_title)
                if (
                    href
                    and title
                    and not re.search(r"\bdemo\b", raw_title, re.IGNORECASE)
                ):
                    yield title, self._site_url(href, url)
            next_link = tree.css_first(".wp-pagenavi a.nextpostslink")
            if not progress or next_link is None:
                return
            href = next_link.attributes.get("href", "")
            if not href:
                raise SourceUnavailable("RomsLab pagination is missing its URL")
            next_url = self._site_url(href, url)
            parsed = urlsplit(next_url)
            if search is None:
                valid = (
                    re.fullmatch(
                        r"/category/switch-games-1/(?:page/[1-9][0-9]*/)?", parsed.path
                    )
                    and not parsed.query
                )
            else:
                valid = re.fullmatch(
                    r"/(?:page/[1-9][0-9]*/)?", parsed.path
                ) and parse_qs(parsed.query) == {"s": [search], "post_type": ["post"]}
            if not valid:
                raise SourceUnavailable("RomsLab returned malformed pagination")
            url = next_url

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        if not self.enabled:
            return []
        titles: dict[str, str] = {}
        for title, _ in self._entries():
            titles.setdefault(title_key(title), title)
            if limit > 0 and len(titles) >= limit:
                break
        return list(titles.values())

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate | None:
        if not self.enabled or not title_key(title):
            return None
        target = title_key(title)
        for found, page in self._entries(clean_title(title)):
            if title_key(found) == target:
                return self._resolve_game(page, target)
        return None

    def _resolve_game(self, page: str, target: str) -> DownloadCandidate:
        tree = HTMLParser(self._get(page))
        heading = tree.css_first("h1.name")
        if (
            heading is None
            or re.search(r"\bdemo\b", heading.text(), re.IGNORECASE)
            or title_key(heading.text(strip=True)) != target
        ):
            raise SourceUnavailable(
                "RomsLab detail title does not match the requested game"
            )
        reasons: list[str] = []
        for link in tree.css(".btns a.btn-download"):
            label = link.text(strip=True)
            if re.search(r"\b(?:update|dlc|part)\b", label, re.IGNORECASE):
                continue
            raw = link.attributes.get("href", "")
            if not raw:
                continue
            try:
                host_page = checked_url(urljoin(page, raw.strip()), self.allowed_hosts)
                filename = unquote(urlsplit(host_page).path.rsplit("/", 1)[-1])
                candidate_for(
                    host_page, filename, self.name, game_page=page, host_page=host_page
                )
                stem = re.split(
                    r"[ _-]+(?:nintendo[ _-]+)?switch(?=[ _.-]|$)",
                    filename,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                if title_key(stem) != target:
                    raise SourceUnavailable(
                        "host filename does not match the requested base game"
                    )
                if label.casefold() != "download here" and not re.search(
                    r"(?:^|[ _-])base(?:[ _.-]|$)", filename, re.IGNORECASE
                ):
                    raise SourceUnavailable(
                        "mirror filename does not identify a base game"
                    )
                host = urlsplit(host_page).hostname
                if host == "datanodes.to":
                    raise SourceUnavailable(
                        "Datanodes base link requires a CAPTCHA; automatic resolution is unsupported"
                    )
                if host != "filekeeper.net":
                    raise SourceUnavailable("unsupported base-game host")
                return self._filekeeper(host_page, filename, page)
            except SourceUnavailable as exc:
                reasons.append(str(exc))
        reason = (
            "; ".join(dict.fromkeys(reasons))
            or "no resolvable base-game link (updates/DLC are not base games)"
        )
        raise SourceUnavailable("RomsLab base game unavailable: " + reason)

    def _filekeeper(
        self, host_page: str, filename: str, game_page: str
    ) -> DownloadCandidate:
        parts = urlsplit(host_page).path.strip("/").split("/")
        if len(parts) != 2 or not re.fullmatch(r"[a-zA-Z0-9]+", parts[0]):
            raise SourceUnavailable("Filekeeper returned an invalid file identity")
        response = self._request("GET", host_page)
        download_page = checked_url(str(response.url), ("filekeeper.net",))
        if (
            urlsplit(download_page).hostname != "filekeeper.net"
            or urlsplit(download_page).path != "/download"
        ):
            raise SourceUnavailable("Filekeeper did not present its download form")
        tree = HTMLParser(response.text)
        form = tree.css_first("#download-countdown")
        if form is None:
            raise SourceUnavailable("Filekeeper download form is unavailable")
        attrs = form.attributes
        if (
            attrs.get("data-has-password") != "false"
            or attrs.get("data-has-captcha") != "false"
            or tree.css_first(".cf-turnstile, .g-recaptcha, input[type=password]")
        ):
            raise SourceUnavailable(
                "Filekeeper requires a password or CAPTCHA; automatic resolution is unsupported"
            )
        if attrs.get("data-code") != parts[0]:
            raise SourceUnavailable("Filekeeper file identity changed")
        countdown = attrs.get("data-countdown") or ""
        if not countdown.isdigit() or not 0 <= int(countdown) <= 60:
            raise SourceUnavailable("Filekeeper has an unsupported countdown")
        time.sleep(int(countdown))
        result = self._request(
            "POST",
            download_page,
            headers={"Referer": download_page},
            data={
                "op": "download2",
                "id": parts[0],
                "rand": attrs.get("data-rand") or "",
                "referer": attrs.get("data-referer") or "",
                "method_free": attrs.get("data-method") or "Free download",
                "down_direct": "1",
            },
            follow_redirects=False,
        )
        location = result.headers.get("Location", "")
        if result.status_code != 302 or not location:
            raise SourceUnavailable(
                "Filekeeper did not issue a direct download redirect"
            )
        direct = checked_url(location, ("dlproxy.uk",))
        if not urlsplit(direct).path.startswith("/download/"):
            raise SourceUnavailable("Filekeeper returned an unsupported download URL")
        metadata = self._request("HEAD", direct)
        if metadata.status_code != 200:
            raise SourceUnavailable("Filekeeper direct download is unavailable")
        disposition = Message()
        disposition["Content-Disposition"] = metadata.headers.get(
            "Content-Disposition", ""
        )
        actual_filename = disposition.get_filename()
        if not actual_filename:
            raise SourceUnavailable(
                "Filekeeper direct download has no filename identity"
            )
        candidate_for(
            direct, actual_filename, self.name, game_page=game_page, host_page=host_page
        )
        if (
            re.sub(r"[ _-]+", " ", actual_filename).casefold()
            != re.sub(r"[ _-]+", " ", filename).casefold()
        ):
            raise SourceUnavailable(
                "Filekeeper direct download filename does not match the base game"
            )
        length = metadata.headers.get("Content-Length", "")
        size = int(length) if length.isdigit() and int(length) > 0 else None
        return candidate_for(
            direct,
            filename,
            self.name,
            game_page=game_page,
            host_page=host_page,
            expected_size=size,
        )
