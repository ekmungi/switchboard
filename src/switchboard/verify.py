# verify.py - Tool-use gate: prove tool_use args survive the proxy round-trip (SPEC-005 R5).
#
# Ported from the Phase-0 spike harness (R-008). Forces a tool call through the local
# proxy in BOTH non-streaming and streaming modes and confirms the arguments arrive
# intact. The streaming check is load-bearing (R-007): LiteLLM has historically dropped
# input_json_delta fragments, leaving Claude Code with empty tool args -- we reassemble
# the fragments and confirm the JSON parses whole with the required key. The HTTP
# transport is injected so units stay hermetic; the default uses stdlib urllib (no new
# runtime dependency). Passing this gate is what marks a model usable.

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

# A tool whose required 'location' arg proves the arguments survived translation.
TOOL: dict = {
    "name": "get_weather",
    "description": "Get the current weather for a given city.",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name, e.g. Paris"},
            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
        },
        "required": ["location"],
    },
}
USER_MSG: str = "What is the weather in Paris right now? You MUST call the get_weather tool."
HEADERS: dict = {
    "content-type": "application/json",
    "anthropic-version": "2023-06-01",
    "x-api-key": "sk-local-proxy-no-auth",  # proxy has no master key; value ignored
}


@dataclass(frozen=True)
class GateResult:
    """Outcome of the tool-use gate.

    Fields:
        ok:            True only when BOTH modes pass (the usable bar).
        non_streaming: Non-streaming tool_use arg check passed.
        streaming:     Streaming reassembly check passed (the R-007 check).
        detail:        Human-readable per-mode detail.
    """

    ok: bool
    non_streaming: bool
    streaming: bool
    detail: str


class Transport(Protocol):
    """Injected HTTP seam: POST an Anthropic /v1/messages body, return (status, lines)."""

    def post(self, url: str, headers: dict, body: dict, stream: bool) -> tuple[int, list[str]]: ...


class UrllibTransport:
    """Default Transport over stdlib urllib (no external HTTP dependency)."""

    def post(self, url: str, headers: dict, body: dict, stream: bool) -> tuple[int, list[str]]:
        """POST *body* to *url*; return (status, [full-text]) or (status, [sse lines])."""
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                status = getattr(resp, "status", 0)
                if stream:
                    return status, [ln.decode("utf-8", "replace") for ln in resp]
                return status, [resp.read().decode("utf-8", "replace")]
        except urllib.error.HTTPError as exc:
            return exc.code, [exc.read().decode("utf-8", "replace")]
        except urllib.error.URLError as exc:
            return 0, [str(exc)]


def _body(model: str, stream: bool) -> dict:
    """Build an Anthropic /v1/messages body that forces the get_weather tool call."""
    return {
        "model": model,
        "max_tokens": 512,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": "get_weather"},  # valid forced-tool shape
        "messages": [{"role": "user", "content": USER_MSG}],
        "stream": stream,
    }


def _eval_nonstreaming(status: int, lines: list[str]) -> tuple[bool, str]:
    """Return (ok, detail): the response must carry a tool_use block with a location."""
    if status != 200:
        return False, f"HTTP {status}"
    try:
        data = json.loads(lines[0]) if lines else {}
    except json.JSONDecodeError:
        return False, "response was not valid JSON"
    for block in data.get("content", []):
        if block.get("type") == "tool_use":
            args = block.get("input", {})
            return bool(args.get("location")), str(args)
    return False, f"no tool_use block (stop_reason={data.get('stop_reason')})"


def _eval_streaming(status: int, lines: list[str]) -> tuple[bool, str]:
    """Return (ok, detail): reassemble input_json_delta fragments; args must be whole."""
    if status != 200:
        return False, f"HTTP {status}"
    partials: list[str] = []
    saw_tool = False
    for raw in lines:
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            break
        try:
            evt = json.loads(payload)
        except json.JSONDecodeError:
            continue
        etype = evt.get("type")
        if etype == "content_block_start" and evt.get("content_block", {}).get("type") == "tool_use":
            saw_tool = True
        elif etype == "content_block_delta":
            delta = evt.get("delta", {})
            if delta.get("type") == "input_json_delta":
                partials.append(delta.get("partial_json", ""))
    if not saw_tool:
        return False, "no tool_use block in stream"
    reassembled = "".join(partials)
    try:
        args = json.loads(reassembled) if reassembled else {}
    except json.JSONDecodeError:
        return False, f"streamed args did not reassemble to valid JSON: {reassembled!r}"
    return bool(args.get("location")), f"raw_len={len(reassembled)}"


def tool_use_gate(base_url: str, model: str, transport: Transport | None = None) -> GateResult:
    """Run the tool-use gate against *model* through the proxy at *base_url*.

    Args:
        base_url:  Proxy base URL (e.g. http://127.0.0.1:4000).
        model:     OpenRouter model id to test.
        transport: Injected HTTP transport (defaults to UrllibTransport).

    Returns:
        GateResult with ok True only when both modes pass.
    """
    tx = transport if transport is not None else UrllibTransport()
    url = base_url.rstrip("/") + "/v1/messages"
    ns_status, ns_lines = tx.post(url, HEADERS, _body(model, False), False)
    ns_ok, ns_detail = _eval_nonstreaming(ns_status, ns_lines)
    st_status, st_lines = tx.post(url, HEADERS, _body(model, True), True)
    st_ok, st_detail = _eval_streaming(st_status, st_lines)
    return GateResult(
        ok=ns_ok and st_ok,
        non_streaming=ns_ok,
        streaming=st_ok,
        detail=f"non-streaming: {ns_detail}; streaming: {st_detail}",
    )
