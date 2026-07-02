# test_health_v3.py - Tests for the pure v3 status/warning helpers (SPEC-004 R5).
#
# Pure-function tests over the conftest blob; no I/O.
# ---------------------------------------------------------------------------

from switchboard.catalog import Model
from switchboard.health_v3 import status_lines_v3, warnings_v3

CAT = [
    Model("deepseek/deepseek-v4-flash", "DeepSeek V4 Flash", 1048576, 9e-08, 0.0),
    Model("z-ai/glm-4.6", "GLM 4.6", 202752, 4e-07, 0.0),
]

APPLIED_OK = "openrouter/deepseek/deepseek-v4-flash"


class TestStatusLinesV3:
    """Tests for status_lines_v3()."""

    def test_healthy_block_content(self, v3_blob):
        lines = status_lines_v3(v3_blob, CAT, True, APPLIED_OK)
        text = "\n".join(lines)
        assert "deepseek/deepseek-v4-flash" in text
        assert "in sync" in text
        assert "CCR running    : yes" in text.replace("  ", " ") or "yes" in text
        assert "WARNINGS" not in text

    def test_drift_marker_present(self, v3_blob):
        lines = status_lines_v3(v3_blob, CAT, True, "openrouter/z-ai/glm-4.6")
        text = "\n".join(lines)
        assert "DRIFT" in text and "session" in text

    def test_missing_applied_named(self, v3_blob):
        text = "\n".join(status_lines_v3(v3_blob, CAT, True, None))
        assert "(none" in text

    def test_router_summary_line(self, v3_blob):
        text = "\n".join(status_lines_v3(v3_blob, CAT, True, APPLIED_OK))
        assert "rules=0" in text and "fallback=off" in text

    def test_warnings_block_appended_when_unhealthy(self, v3_blob):
        v3_blob["APIKEY"] = "x"
        lines = status_lines_v3(v3_blob, CAT, True, APPLIED_OK)
        assert "WARNINGS:" in lines


class TestWarningsV3:
    """Tests for warnings_v3()."""

    def test_empty_when_healthy(self, v3_blob):
        assert warnings_v3(v3_blob, CAT, APPLIED_OK) == []

    def test_leak_model_warned(self, v3_blob):
        v3_blob["profile"]["profiles"][0]["model"] = "openrouter/anthropic/claude-x"
        warns = warnings_v3(v3_blob, CAT, "openrouter/anthropic/claude-x")
        assert any("Anthropic" in w for w in warns)

    def test_whitelist_miss_warned(self, v3_blob):
        v3_blob["Providers"][0]["models"] = []
        warns = warnings_v3(v3_blob, CAT, APPLIED_OK)
        assert any("whitelist" in w.lower() for w in warns)

    def test_drift_warned(self, v3_blob):
        warns = warnings_v3(v3_blob, CAT, "openrouter/z-ai/glm-4.6")
        assert any("drift" in w.lower() for w in warns)

    def test_websearch_on_billing_warned(self, v3_blob):
        v3_blob["profile"]["profiles"][0]["model"] += ":online"
        warns = warnings_v3(v3_blob, CAT, None)
        assert any("billed" in w.lower() or "online" in w.lower() for w in warns)

    def test_nonblank_apikey_warned(self, v3_blob):
        v3_blob["APIKEY"] = "x"
        warns = warnings_v3(v3_blob, CAT, APPLIED_OK)
        assert any("APIKEY" in w for w in warns)
