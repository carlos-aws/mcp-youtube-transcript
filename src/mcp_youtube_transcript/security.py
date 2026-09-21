"""Input and network bounds for the personal research deployment."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

DEFAULT_RESPONSE_LIMIT = 15_000
MAX_RESPONSE_LIMIT = 50_000
MAX_TRANSCRIPT_CHARS = 1_000_000
MAX_SNIPPETS = 50_000
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def parse_video_id(url: str) -> str:
    """Accept only an HTTPS YouTube video URL, never an arbitrary destination."""
    if not isinstance(url, str) or len(url) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", url):
        raise ValueError("Expected a valid HTTPS YouTube video URL")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in VIDEO_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        raise ValueError("Expected an HTTPS YouTube video URL without credentials or a port")
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.removeprefix("/")
    elif parsed.path == "/watch" and parsed.hostname not in {"youtube-nocookie.com", "www.youtube-nocookie.com"}:
        values = parse_qs(parsed.query).get("v", [])
        video_id = values[0] if len(values) == 1 else ""
    else:
        parts = parsed.path.split("/")
        video_id = parts[2] if len(parts) == 3 and parts[1] in {"shorts", "embed", "live"} else ""
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("Expected one 11-character YouTube video ID")
    return video_id


def canonical_video_url(url: str) -> str:
    return f"https://www.youtube.com/watch?v={parse_video_id(url)}"


def language(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})*", value):
        raise ValueError("Expected a language code such as en or pt-BR")
    if len(value) > 35:
        raise ValueError("Language code is too long")
    return value


def cursor(value: str | None, maximum: int) -> int:
    if value is None:
        return 0
    if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", value):
        raise ValueError("Invalid pagination cursor")
    result = int(value)
    if result > maximum:
        raise ValueError("Pagination cursor is outside this transcript")
    return result


def response_limit(value: int | None) -> int:
    value = DEFAULT_RESPONSE_LIMIT if value is None else value
    if type(value) is not int or not 1024 <= value <= MAX_RESPONSE_LIMIT:
        raise ValueError("Response limit must be between 1024 and 50000 characters")
    return value


class ResearchSession(requests.Session):
    """Ignore ambient .netrc/proxies and apply timeouts to every request/redirect."""

    def __init__(self) -> None:
        super().__init__()
        self.trust_env = False
        self.max_redirects = 3

    def send(self, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        parsed = urlsplit(request.url or "")
        host = parsed.hostname or ""
        allowed = host in {"youtube.com", "youtubei.googleapis.com"} or host.endswith(
            (".youtube.com", ".googlevideo.com")
        )
        if (
            parsed.scheme != "https"
            or not allowed
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
        ):
            raise ValueError("Transcript request destination is not an approved YouTube HTTPS endpoint")
        kwargs["timeout"] = (5, 20)
        return super().send(request, **kwargs)


class PrivateDownloadLogger:
    """Do not expose proxy URLs or third-party exception text in MCP logs."""

    def debug(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass

    def error(self, _message: str) -> None:
        pass
