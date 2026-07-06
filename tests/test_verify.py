# test_verify.py - Tool-use gate: tool_use args survive the proxy round-trip (SPEC-005 R5).
#
# Hermetic: the HTTP transport is injected (canned Anthropic responses); no proxy or
# network is touched. Mirrors the Phase-0 spike gate (non-streaming + streaming).

import json

from switchboard import verify
from switchboard.verify import GateResult


def sse(evt: dict) -> str:
    """Build one Anthropic SSE line from an event dict."""
    return "data: " + json.dumps(evt)


# A non-streaming body carrying a tool_use block with a non-empty location arg.
GOOD_NONSTREAM = json.dumps(
    {"content": [{"type": "tool_use", "name": "get_weather", "input": {"location": "Paris"}}],
     "stop_reason": "tool_use"}
)

# Streamed fragments that reassemble to {"location": "Paris"} (the R-007 check).
GOOD_STREAM = [
    sse({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "get_weather"}}),
    sse({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"location":'}}),
    sse({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": ' "Paris"}'}}),
    "data: [DONE]",
]


class FakeTransport:
    """Injected transport returning canned (status, lines) per mode."""

    def __init__(self, nonstream, stream):
        self._ns = nonstream
        self._st = stream
        self.calls = []

    def post(self, url, headers, body, stream):
        self.calls.append(("stream" if stream else "ns", body["model"]))
        return self._st if stream else self._ns


class TestToolUseGate:
    """Tests for tool_use_gate(base_url, model, transport)."""

    def test_passes_when_both_modes_carry_tool_args(self):
        """Both modes return a tool_use with a real location -> gate passes."""
        t = FakeTransport((200, [GOOD_NONSTREAM]), (200, GOOD_STREAM))
        r = verify.tool_use_gate("http://127.0.0.1:4000", "deepseek/deepseek-chat", transport=t)
        assert isinstance(r, GateResult)
        assert r.ok is True and r.non_streaming is True and r.streaming is True

    def test_sends_the_model_to_the_proxy(self):
        """The requested model reaches the transport in both calls."""
        t = FakeTransport((200, [GOOD_NONSTREAM]), (200, GOOD_STREAM))
        verify.tool_use_gate("http://127.0.0.1:4000", "z-ai/glm-4.6", transport=t)
        assert t.calls == [("ns", "z-ai/glm-4.6"), ("stream", "z-ai/glm-4.6")]

    def test_fails_when_nonstreaming_has_no_tool_use(self):
        """A response with no tool_use block fails the non-streaming half."""
        no_tool = json.dumps({"content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn"})
        t = FakeTransport((200, [no_tool]), (200, GOOD_STREAM))
        r = verify.tool_use_gate("http://127.0.0.1:4000", "m", transport=t)
        assert r.ok is False and r.non_streaming is False

    def test_fails_on_non_200(self):
        """A provider/proxy error status fails the gate with the status in detail."""
        t = FakeTransport((500, ["upstream error"]), (200, GOOD_STREAM))
        r = verify.tool_use_gate("http://127.0.0.1:4000", "m", transport=t)
        assert r.ok is False and r.non_streaming is False
        assert "500" in r.detail

    def test_fails_when_streamed_args_do_not_reassemble(self):
        """Dropped/garbled input_json_delta fragments fail the streaming half (R-007)."""
        broken = [
            sse({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "get_weather"}}),
            sse({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"loc'}}),
            "data: [DONE]",
        ]
        t = FakeTransport((200, [GOOD_NONSTREAM]), (200, broken))
        r = verify.tool_use_gate("http://127.0.0.1:4000", "m", transport=t)
        assert r.ok is False and r.streaming is False

    def test_fails_when_streamed_args_lack_required_location(self):
        """Reassembles to valid JSON but without the required arg -> streaming fails."""
        no_loc = [
            sse({"type": "content_block_start", "content_block": {"type": "tool_use", "name": "get_weather"}}),
            sse({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": '{"unit": "c"}'}}),
            "data: [DONE]",
        ]
        t = FakeTransport((200, [GOOD_NONSTREAM]), (200, no_loc))
        r = verify.tool_use_gate("http://127.0.0.1:4000", "m", transport=t)
        assert r.ok is False and r.streaming is False
