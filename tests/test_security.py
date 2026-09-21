"""Offline regressions for inputs, credential handling and bounded output."""

from collections.abc import Callable
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
import requests
from mcp.server.mcpserver.exceptions import ToolError
from youtube_transcript_api import FetchedTranscriptSnippet

import mcp_youtube_transcript as module
from mcp_youtube_transcript.security import ResearchSession, canonical_video_url, cursor, language

VIDEO_URL = "https://www.youtube.com/watch?v=tACfRW2f8ao"


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/watch?v=tACfRW2f8ao",
        "https://www.youtube.com.attacker.example/watch?v=tACfRW2f8ao",
        "https://www.youtube.com@attacker.example/watch?v=tACfRW2f8ao",
        "https://user:password@www.youtube.com/watch?v=tACfRW2f8ao",
        "http://www.youtube.com/watch?v=tACfRW2f8ao",
        "file:///etc/passwd?v=tACfRW2f8ao",
        "https://127.0.0.1/watch?v=tACfRW2f8ao",
        "https://www.youtube.com:443/watch?v=tACfRW2f8ao",
        "https://www.youtube.com/watch?v=tACfRW2f8ao&v=AAAAAAAAAAA",
        "https://youtu.be/tACfRW2f8ao/extra",
        "https://www.youtube.com/shorts/",
        "https://www.youtube.com/watch?v=a",
        "https://www.youtube.com/watch?v=tACfRW2f8ao\n",
    ],
)
def test_rejects_unapproved_or_ambiguous_video_urls(url: str) -> None:
    with pytest.raises(ValueError):
        canonical_video_url(url)


def test_tracking_and_fragment_are_not_sent_to_youtube() -> None:
    assert canonical_video_url(VIDEO_URL + "&tracking=private#arbitrary") == VIDEO_URL


@pytest.mark.parametrize("value", ["-1", "1.2", "10000000", "not-a-cursor", "00"])
def test_cursor_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        cursor(value, 100)


def test_cursor_checks_transcript_bounds() -> None:
    with pytest.raises(ValueError):
        cursor("101", 100)


@pytest.mark.parametrize("value", ["en\r\nSecret: value", "en;run", "x" * 100, ""])
def test_language_cannot_be_a_header_or_instruction(value: str) -> None:
    with pytest.raises(ValueError):
        language(value)


def test_session_ignores_ambient_credentials_and_enforces_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret@localhost:1234")
    monkeypatch.setattr(requests.sessions, "get_netrc_auth", Mock(side_effect=AssertionError("Read .netrc")))
    transport = Mock(return_value=requests.Response())
    monkeypatch.setattr(requests.Session, "send", transport)
    with ResearchSession() as session:
        request = session.prepare_request(requests.Request("GET", VIDEO_URL))
        assert "Authorization" not in request.headers
        assert not session.trust_env
        session.send(request, timeout=None)
        assert transport.call_args.kwargs["timeout"] == (5, 20)
        for destination in ("http://www.youtube.com/", "https://127.0.0.1/", "https://attacker.example/"):
            bad_request = session.prepare_request(requests.Request("GET", destination))
            with pytest.raises(ValueError):
                session.send(bad_request)
        assert transport.call_count == 1


@pytest.mark.anyio
async def test_lifespan_disables_local_plugins_files_cookies_and_javascript() -> None:
    mcp = module.server()
    lifespan = mcp.settings.lifespan
    assert lifespan is not None
    async with lifespan(mcp) as context:
        params = context.dlp.params
        assert params["cachedir"] is False
        assert params["enable_file_urls"] is False
        assert params["usenetrc"] is False
        assert params["cookiefile"] is None
        assert params["cookiesfrombrowser"] is None
        assert params["js_runtimes"] == {}
        assert params["remote_components"] == set()
        assert params["socket_timeout"] == 20
        assert params["proxy"] == ""


@pytest.mark.anyio
async def test_tools_are_explicitly_read_only_and_source_data_is_untrusted() -> None:
    mcp = module.server()
    assert mcp.instructions is not None
    assert "untrusted" in mcp.instructions
    tools = await mcp.list_tools()
    assert {t.name for t in tools} == {
        "get_transcript",
        "get_timed_transcript",
        "get_video_info",
        "get_available_languages",
    }
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint
        assert tool.annotations.destructive_hint is False


def tool_function(name: str, monkeypatch: pytest.MonkeyPatch, text: str) -> Callable[[str | None], Any]:
    monkeypatch.setattr(
        module,
        "_get_transcript_snippets",
        lambda *args: (
            "Source title",
            [FetchedTranscriptSnippet(text=text, start=0, duration=3)],
        ),
    )
    mcp = module.server(response_limit=1024)
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=object()))
    return lambda next_cursor: tool.fn(ctx=context, url=VIDEO_URL, lang="en", next_cursor=next_cursor)


def test_long_plain_snippet_always_makes_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    text = "x" * 3000
    invoke = tool_function("get_transcript", monkeypatch, text)
    next_cursor = None
    pages = []
    for _ in range(4):
        page = invoke(next_cursor)
        assert page.source_url == VIDEO_URL
        assert page.untrusted_content
        assert 0 < len(page.transcript) <= 1024
        pages.append(page.transcript)
        if page.next_cursor is None:
            break
        assert page.next_cursor != next_cursor
        next_cursor = page.next_cursor
    assert "".join(pages) == text


def test_oversized_timed_snippet_fails_instead_of_repeating_a_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    invoke = tool_function("get_timed_transcript", monkeypatch, "x" * 3000)
    with pytest.raises(ToolError, match="use get_transcript"):
        invoke(None)


def test_invalid_cursor_is_rejected_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    fetch = Mock(side_effect=AssertionError("Made a network request"))
    monkeypatch.setattr(module, "_get_transcript_snippets", fetch)
    tool = module.server()._tool_manager.get_tool("get_transcript")
    assert tool is not None
    context = SimpleNamespace(request_context=SimpleNamespace(lifespan_context=object()))
    with pytest.raises(ValueError):
        tool.fn(ctx=context, url=VIDEO_URL, lang="en", next_cursor="-1")
    fetch.assert_not_called()


def test_proxy_error_is_not_returned_to_the_model() -> None:
    context = module.AppContext(Mock(), Mock(), Mock())
    context.dlp.extract_info.side_effect = RuntimeError("https://proxy-user:secret@proxy.invalid")
    with pytest.raises(ToolError) as error:
        module._get_video_info(context, VIDEO_URL)
    assert "secret" not in str(error.value)
    assert "proxy-user" not in str(error.value)


def test_metadata_is_bounded_and_uses_a_real_epoch_timestamp() -> None:
    context = module.AppContext(Mock(), Mock(), Mock())
    context.dlp.extract_info.return_value = {
        "title": "t" * 600,
        "description": "d" * 9000,
        "uploader": "u" * 300,
        "timestamp": 1650496000,
        "upload_date": "20220421",
        "duration": None,
    }
    info = module._get_video_info(context, VIDEO_URL + "&tracking=private")
    assert info.upload_date == datetime.fromtimestamp(1650496000, timezone.utc)
    assert len(info.title) == 500 and len(info.description) == 8000 and len(info.uploader) == 200
    assert set(info.truncated_fields) == {"title", "description", "uploader"}
    context.dlp.extract_info.assert_called_once_with(VIDEO_URL, download=False)


@pytest.mark.parametrize("value", [0, -1, True, 100_000])
def test_unbounded_or_ambiguous_response_configuration_is_rejected(value: int) -> None:
    with pytest.raises(ValueError):
        module.server(response_limit=value)
