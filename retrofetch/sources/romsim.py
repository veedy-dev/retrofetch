from __future__ import annotations

import re
from collections.abc import Iterator
from urllib.parse import urlencode, urljoin, urlsplit

from selectolax.parser import HTMLParser

from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._switch_archive import (
    SwitchArchiveSource,
    candidate_for,
    checked_url,
    clean_title,
    title_key,
)


class RomsimSource(SwitchArchiveSource):
    name = "romsim"
    base_url = "https://romsim.net/"
    allowed_hosts = (
        "romsim.net",
        "bzzhr.to",
        "buzzheavier.com",
        "buffdrive.com",
        "buffdrive.xyz",
    )

    def _site_url(self, href: str, root: str) -> str:
        try:
            url = checked_url(
                urljoin(root, href), (urlsplit(self.base_url).hostname or "",)
            )
        except ValueError as exc:
            raise SourceUnavailable("ROMsIM returned a malformed catalog link") from exc
        if urlsplit(url).hostname != urlsplit(self.base_url).hostname:
            raise SourceUnavailable("ROMsIM returned an offsite catalog link")
        return url

    def _posts(self, index: str, selector: str) -> Iterator[tuple[str, str]]:
        page = index
        visited: set[str] = set()
        seen: set[str] = set()
        root = urlsplit(index).path.rstrip("/")
        while page not in visited:
            visited.add(page)
            tree = HTMLParser(self._get(page))
            progress = False
            for anchor in tree.css(selector):
                href = (anchor.attributes.get("href") or "").strip()
                if not href or href.startswith(("#", "?")):
                    raise SourceUnavailable("ROMsIM returned a malformed game link")
                url = self._site_url(href, self.base_url + "/")
                raw_title = anchor.text(separator=" ", strip=True)
                if re.search(r"\bdemo\b", raw_title, re.IGNORECASE):
                    continue
                title = clean_title(raw_title)
                key = title_key(title)
                if key and key not in seen:
                    seen.add(key)
                    progress = True
                    yield title, url
            next_link = tree.css_first(".pages-nav .the-next-page a[href]")
            if not progress or next_link is None:
                return
            # ROMsIM's page/N/ links are archive-root relative, not current-page relative.
            page = self._site_url((next_link.attributes["href"] or ""), index)
            parts = urlsplit(page)
            if not re.fullmatch(re.escape(root) + r"/page/[1-9]\d*/?", parts.path):
                raise SourceUnavailable("ROMsIM returned a malformed pagination link")
            if urlsplit(index).query and not parts.query:
                page += "?" + urlsplit(index).query

    def list_popular(
        self, limit: int, region_priority: list[str] | None = None
    ) -> list[str]:
        if not self.enabled:
            return []
        titles: list[str] = []
        for title, _ in self._posts(
            self.base_url.rstrip("/") + "/top-games/", "h2.post-title a[href]"
        ):
            titles.append(title)
            if limit > 0 and len(titles) >= limit:
                break
        return titles

    def find_url_for_game(
        self, title: str, region_priority: list[str] | None = None
    ) -> DownloadCandidate | None:
        if not self.enabled:
            return None
        index = self.base_url.rstrip("/") + "/?" + urlencode({"s": title})
        for found, page in self._posts(index, "h2.thumb-title a[href]"):
            if title_key(found) == title_key(title):
                return self._resolve_game(page, title)
        return None

    def _resolve_game(self, page: str, expected_title: str) -> DownloadCandidate:
        tree = HTMLParser(self._get(page))
        heading = tree.css_first("h1")
        actual_title = heading.text(separator=" ", strip=True) if heading else ""
        if (
            not actual_title
            or re.search(r"\bdemo\b", actual_title, re.IGNORECASE)
            or title_key(actual_title) != title_key(expected_title)
        ):
            raise SourceUnavailable(
                "ROMsIM detail title does not match the selected game"
            )
        content = tree.css_first(".entry-content")
        bases: list[list[str]] = []
        in_downloads = False
        if content is not None:
            for node in content.css("h4, p"):
                if node.tag == "h4":
                    in_downloads = node.text(strip=True).casefold() == "download links"
                    continue
                label = node.css_first("strong")
                if not in_downloads or label is None:
                    continue
                text = label.text(separator=" ", strip=True)
                if not re.match(r"^BASE\s+GAME\b", text, re.IGNORECASE):
                    continue
                if re.search(
                    r"\b(update|dlc|part\s*\d+)\b",
                    node.text(separator=" "),
                    re.IGNORECASE,
                ):
                    raise SourceUnavailable("ROMsIM base game is bundled or multipart")
                bases.append(
                    [
                        (a.attributes["href"] or "")
                        for a in node.css("a.shortc-button[href]")
                    ]
                )
        if len(bases) != 1 or not bases[0]:
            raise SourceUnavailable("ROMsIM has no unambiguous base-game mirrors")
        failures: list[str] = []
        mirrors = list(dict.fromkeys(bases[0]))
        try:
            hosts = [urlsplit(urljoin(page, href)).hostname for href in mirrors]
        except ValueError as exc:
            raise SourceUnavailable("ROMsIM returned a malformed mirror link") from exc
        if len(set(hosts)) != len(hosts):
            raise SourceUnavailable("ROMsIM has ambiguous same-host base-game files")
        for href in mirrors:
            host_page = urljoin(page, href)
            host = urlsplit(host_page).hostname or ""
            if host == "gofile.io" or host.endswith(".gofile.io"):
                failures.append("GoFile requires an unsupported resolver")
                continue
            try:
                host_page = checked_url(host_page, self.allowed_hosts)
                if host in ("bzzhr.to", "buzzheavier.com"):
                    return self._buzzheavier(host_page, page, expected_title)
                if host == "buffdrive.com":
                    return self._buffdrive(host_page, page, expected_title)
                failures.append("unsupported base-game host")
            except SourceUnavailable as exc:
                failures.append(str(exc))
        raise SourceUnavailable(
            "ROMsIM base-game mirrors unavailable: " + "; ".join(failures)
        )

    def _buzzheavier(
        self, host_page: str, game_page: str, expected_title: str
    ) -> DownloadCandidate:
        if not re.fullmatch(r"/[A-Za-z0-9]+/?", urlsplit(host_page).path):
            raise SourceUnavailable("Buzzheavier legacy/folder links are unsupported")
        tree = HTMLParser(self._get(host_page))
        title = tree.css_first("title")
        buttons = tree.css("a.download-btn[hx-get]")
        if title is None or len(buttons) != 1:
            raise SourceUnavailable(
                "Buzzheavier did not provide a single-file download"
            )
        filename = title.text(strip=True)
        self._check_filename(filename, expected_title)
        endpoint = checked_url(
            urljoin(host_page, (buttons[0].attributes["hx-get"] or "")),
            ("bzzhr.to", "buzzheavier.com"),
        )
        if (
            urlsplit(endpoint).hostname != urlsplit(host_page).hostname
            or urlsplit(endpoint).path
            != urlsplit(host_page).path.rstrip("/") + "/download"
        ):
            raise SourceUnavailable("Buzzheavier returned an invalid download endpoint")
        response = self._request(
            "GET",
            endpoint,
            headers={
                "HX-Request": "true",
                "HX-Current-URL": host_page,
                "Referer": host_page,
            },
            follow_redirects=False,
        )
        direct = response.headers.get("HX-Redirect")
        if response.status_code != 204 or not direct:
            raise SourceUnavailable(
                "Buzzheavier challenge or download redirect unavailable"
            )
        return candidate_for(
            checked_url(direct, ("bzzhr.to", "buzzheavier.com")),
            filename,
            self.name,
            game_page=game_page,
            host_page=host_page,
        )

    def _buffdrive(
        self, host_page: str, game_page: str, expected_title: str
    ) -> DownloadCandidate:
        if not re.fullmatch(r"/[A-Za-z0-9]+/?", urlsplit(host_page).path):
            raise SourceUnavailable("Buffdrive requires a single-file page")
        tree = HTMLParser(self._get(host_page))
        title = tree.css_first("title")
        endpoints: set[str] = set()
        for node in tree.css("[onclick]"):
            match = re.fullmatch(
                r"\s*window\.location\s*=\s*(['\"])([^'\"]+)\1\s*;\s*return\s+false\s*;?\s*",
                (node.attributes["onclick"] or ""),
            )
            if match:
                endpoints.add(checked_url(match[2], ("buffdrive.com",)))
        if title is None or len(endpoints) != 1:
            raise SourceUnavailable(
                "Buffdrive did not provide one supported download button"
            )
        filename = re.sub(
            r"\s+-\s+BUFFDRIVE\s*$", "", title.text(strip=True), flags=re.IGNORECASE
        )
        self._check_filename(filename, expected_title)
        endpoint = endpoints.pop()
        if (
            urlsplit(endpoint).hostname != "buffdrive.com"
            or urlsplit(endpoint).path != urlsplit(host_page).path
            or not urlsplit(endpoint).query.startswith("pt=")
        ):
            raise SourceUnavailable("Buffdrive returned an invalid download endpoint")
        response = self._request(
            "GET",
            endpoint,
            headers={"Referer": host_page},
            follow_redirects=False,
        )
        direct = response.headers.get("Location")
        if response.status_code != 302 or not direct:
            raise SourceUnavailable("Buffdrive download redirect unavailable")

        return candidate_for(
            checked_url(direct, ("buffdrive.xyz",)),
            filename,
            self.name,
            game_page=game_page,
            host_page=host_page,
        )

    @staticmethod
    def _check_filename(filename: str, expected_title: str) -> None:
        match = re.fullmatch(
            r"(.+)-BASE(?:-(?:NSP|XCI|NSZ|XCZ))?(?:-Romsim(?:\.com)?)?\.(?:rar|zip|7z|nsp|xci|nsz|xcz)",
            filename,
            re.IGNORECASE,
        )
        if match is None or title_key(match[1]) != title_key(expected_title):
            raise SourceUnavailable(
                "ROMsIM host file does not match the selected base game"
            )
