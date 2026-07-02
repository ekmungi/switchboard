# test_cli_v3_dispatch.py - cli.py routes commands to the v3 layer on a v3 store.
#
# Hermetic: detect_store + v3 command functions monkeypatched with recorders;
# the legacy write path is instrumented to prove it is never touched on v3.
# ---------------------------------------------------------------------------

import pytest

from switchboard import cli
from switchboard.catalog import Model

CAT = [Model("z-ai/glm-4.6", "GLM 4.6", 202752, 4e-07, 0.0)]


@pytest.fixture
def v3(monkeypatch):
    """Force the v3 branch and forbid legacy config writes."""
    monkeypatch.setattr(cli, "detect_store", lambda: "v3")
    def _forbidden(cfg):
        raise AssertionError("legacy write_config must not run on a v3 store")
    monkeypatch.setattr(cli, "write_config", _forbidden)
    return monkeypatch


class TestDispatchV3:
    """Store-detection branching for each command."""

    def test_current_routes_to_v3(self, v3):
        calls = []
        v3.setattr(cli, "current_v3", lambda md: calls.append(md))
        cli.cmd_current()
        assert calls == [False]

    def test_doctor_routes_to_v3(self, v3):
        calls = []
        v3.setattr(cli, "doctor_v3", lambda: calls.append(True))
        cli.cmd_doctor()
        assert calls == [True]

    def test_use_validates_then_routes_to_v3(self, v3):
        calls = []
        v3.setattr(cli, "fetch_models", lambda: CAT)
        v3.setattr(cli, "use_v3", lambda model_id, model: calls.append(model_id))
        cli.cmd_use("z-ai/glm-4.6")
        assert calls == ["z-ai/glm-4.6"]

    def test_use_still_refuses_invalid_model_before_branching(self, v3, capsys):
        v3.setattr(cli, "fetch_models", lambda: CAT)
        v3.setattr(cli, "use_v3", lambda model_id, model: pytest.fail("must not reach v3"))
        with pytest.raises(SystemExit):
            cli.cmd_use("nope/nope")

    def test_websearch_routes_to_v3(self, v3):
        calls = []
        v3.setattr(cli, "websearch_v3", lambda state: calls.append(state))
        cli.cmd_websearch("off")
        assert calls == ["off"]

    def test_websearch_invalid_state_exits_before_branching(self, v3, capsys):
        v3.setattr(cli, "websearch_v3", lambda state: pytest.fail("must not reach v3"))
        with pytest.raises(SystemExit):
            cli.cmd_websearch("banana")
