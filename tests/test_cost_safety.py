# test_cost_safety.py - The single cost-safety guard shared by config-gen + doctor (R3a/R5a).

from switchboard import cost_safety


class TestUnsafeReason:
    """Tests for unsafe_reason(target)."""

    def test_none_for_a_cheap_concrete_model(self):
        """A concrete OpenRouter model id is safe."""
        assert cost_safety.unsafe_reason("deepseek/deepseek-chat") is None

    def test_flags_anthropic_priced_model(self):
        """anthropic/* is Claude-priced -> reason mentions the risk."""
        reason = cost_safety.unsafe_reason("anthropic/claude-3-5-sonnet")
        assert reason is not None and "anthropic" in reason.lower()

    def test_flags_passthrough_wildcard(self):
        """A trailing /* passthrough is flagged."""
        assert cost_safety.unsafe_reason("openrouter/*") is not None

    def test_flags_bare_wildcard(self):
        """A bare '*' is flagged."""
        assert cost_safety.unsafe_reason("*") is not None

    def test_flags_empty(self):
        """An empty/whitespace target is flagged."""
        assert cost_safety.unsafe_reason("   ") is not None


class TestIsSafe:
    """Tests for is_safe(target)."""

    def test_true_for_safe(self):
        assert cost_safety.is_safe("z-ai/glm-4.6") is True

    def test_false_for_anthropic(self):
        assert cost_safety.is_safe("anthropic/claude-3-haiku") is False
