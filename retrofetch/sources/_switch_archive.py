"""Shared metadata transport and safe HTTP transfers for Switch archives."""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urljoin, urlsplit

from curl_cffi.requests import Response, Session

from retrofetch.downloader import finalize_staged_candidate, stream_http_download
from retrofetch.events import EventBus
from retrofetch.sanitize import sanitize_filename
from retrofetch.sources import DownloadCandidate, SourceUnavailable
from retrofetch.sources._cloudflare_base import (
    CloudflareBlocked,
    health,
    is_cloudflare_challenge,
    is_dead,
)

_FORMAT_SUFFIX = re.compile(
    r"\s+(?:Nintendo\s+)?Switch(?=\s+(?:NSP|XCI|NSZ|XCZ|Free\b|ROM\b)|\s*$).*$",
    re.IGNORECASE,
)
_NON_BASE = re.compile(
    r"(?:^|[\s._\-\[(])(?:updates?|dlcs?|upd)(?=[\s._\-\])\d]|$)",
    re.IGNORECASE,
)
_MULTIPART = re.compile(r"[._ -]part[._ -]*\d+\.(?:rar|zip|7z)$", re.IGNORECASE)
_PAYLOAD_SUFFIXES = {".nsp", ".xci", ".nsz", ".xcz", ".zip", ".7z", ".rar"}
_MAX_METADATA_BYTES = 4 * 1024 * 1024


def checked_url(url: str, hosts: tuple[str, ...]) -> str:
    """Keep untrusted page links and redirects on explicitly supported HTTPS hosts."""
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower()
        valid = (
            parts.scheme == "https"
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and not parts.fragment
            and not any(ord(char) < 32 for char in url)
            and any(
                host == allowed or host.endswith("." + allowed) for allowed in hosts
            )
        )
    except ValueError:
        valid = False
    if not valid:
        raise SourceUnavailable(
            "archive returned an unsupported or unsafe URL", retryable=False
        )
    return url.strip()


def clean_title(text: str) -> str:
    text = " ".join(text.split())
    return _FORMAT_SUFFIX.sub("", text).strip()


def title_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_title(text)).casefold()
    return "".join(char for char in normalized if char.isalnum())


def candidate_for(
    url: str,
    filename: str,
    source: str,
    *,
    game_page: str,
    host_page: str,
    expected_size: int | None = None,
) -> DownloadCandidate:
    filename = unquote(filename.strip())
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or any(ord(char) < 32 for char in filename)
        or Path(filename).suffix.lower() not in _PAYLOAD_SUFFIXES
        or _NON_BASE.search(filename)
        or _MULTIPART.search(filename)
    ):
        raise SourceUnavailable(
            "archive link is not a standalone base-game file", retryable=False
        )
    return DownloadCandidate(
        url=url,
        filename=sanitize_filename(filename),
        source=source,
        expected_size=expected_size,
        extra={"game_page": game_page, "host_page": host_page},
    )


class SwitchArchiveSource:
    name: str
    base_url: str
    allowed_hosts: tuple[str, ...]

    def __init__(
        self, console_entry: dict[str, Any], base_url: str | None = None
    ) -> None:
        self.enabled = console_entry.get("shortname") == "switch"
        self.base_url = (base_url or self.base_url).rstrip("/") + "/"
        self.allowed_hosts = (
            *self.allowed_hosts,
            urlsplit(self.base_url).hostname or "",
        )
        self._session: Session | None = None

    def _request(
        self,
        method: Literal["GET", "POST", "HEAD"],
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Response:
        if is_dead(self.name):
            raise SourceUnavailable(f"{self.name} marked dead for session")
        if self._session is None:
            # Browser-compatible TLS, not a CAPTCHA solver. Challenges fail closed.
            self._session = Session(impersonate="chrome")
        try:
            for _ in range(6):
                url = checked_url(url, self.allowed_hosts)
                time.sleep(0.25)
                response = self._session.request(
                    method,
                    url,
                    headers=headers,
                    data=data,
                    timeout=30,
                    allow_redirects=False,
                    stream=True,
                )
                try:
                    redirect = response.status_code in (301, 302, 303, 307, 308)
                    if (
                        not redirect
                        and method != "HEAD"
                        and response.status_code != 204
                    ):
                        content_type = response.headers.get("Content-Type", "").lower()
                        if "text/html" not in content_type:
                            raise SourceUnavailable(
                                f"{self.name} expected an HTML metadata page",
                                retryable=False,
                            )
                        chunks: list[bytes] = []
                        size = 0
                        for chunk in response.iter_content():
                            size += len(chunk)
                            if size > _MAX_METADATA_BYTES:
                                raise SourceUnavailable(
                                    f"{self.name} metadata page is too large",
                                    retryable=False,
                                )
                            chunks.append(chunk)
                        response.content = b"".join(chunks)
                finally:
                    response.close()
                if is_cloudflare_challenge(response.text):
                    raise CloudflareBlocked(
                        f"{self.name} requires an interactive Cloudflare challenge",
                        retryable=False,
                    )
                if response.status_code >= 400:
                    raise SourceUnavailable(
                        f"{self.name} HTTP {response.status_code}",
                        retryable=response.status_code in (408, 429)
                        or response.status_code >= 500,
                    )
                if redirect and follow_redirects:
                    location = response.headers.get("Location")
                    if not location:
                        raise SourceUnavailable(
                            f"{self.name} redirect has no destination", retryable=False
                        )
                    next_url = checked_url(urljoin(url, location), self.allowed_hosts)
                    if urlsplit(next_url).hostname != urlsplit(url).hostname:
                        headers = None
                    if response.status_code == 303 or (
                        method == "POST" and response.status_code in (301, 302)
                    ):
                        method, data = "GET", None
                    url = next_url
                    continue
                health(self.name).record_success()
                return response
            raise SourceUnavailable(
                f"{self.name} too many metadata redirects", retryable=False
            )
        except SourceUnavailable:
            health(self.name).record_failure()
            raise
        except Exception as exc:
            health(self.name).record_failure()
            # HTTP exception messages can contain signed URLs and host tokens.
            raise SourceUnavailable(
                f"{self.name} metadata request failed ({type(exc).__name__})"
            ) from exc

    def _get(self, url: str) -> str:
        return self._request("GET", url).text

    def download(
        self,
        candidate: DownloadCandidate,
        dest_dir: Path,
        *,
        event_bus: EventBus | None = None,
    ) -> Path:
        checked_url(candidate.url, self.allowed_hosts)
        if (
            candidate.source != self.name
            or Path(candidate.filename).name != candidate.filename
            or "\\" in candidate.filename
        ):
            raise SourceUnavailable(
                "archive candidate identity is invalid", retryable=False
            )
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = sanitize_filename(candidate.filename, str(dest_dir))
        destination = dest_dir / filename
        if destination.exists() or destination.is_symlink():
            raise SourceUnavailable(
                "refusing to overwrite an existing archive file", retryable=False
            )
        staging = dest_dir / f".retrofetch-{self.name}"
        if staging.is_symlink() or (staging.exists() and not staging.is_dir()):
            raise SourceUnavailable(
                "archive staging directory is not a regular directory", retryable=False
            )
        staging.mkdir(exist_ok=True)
        staged = staging / sanitize_filename(candidate.filename, str(staging))
        part = staged.with_suffix(staged.suffix + ".part")
        for path in (staged, part):
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise SourceUnavailable(
                    "archive staging file is not a regular file", retryable=False
                )
        stream_http_download(
            candidate.url,
            staged,
            event_bus=event_bus,
            event_game=candidate.filename,
            source_name=self.name,
            expected_size=candidate.expected_size,
        )
        return finalize_staged_candidate(
            staged,
            staging_root=staging,
            target_dir=dest_dir,
            candidate=candidate,
        ).path
