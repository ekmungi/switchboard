# test_sync_cmd.py - Tests for the sync subcommand orchestration & report.
#
# Hermetic: all config paths redirected to tmp_path; apply layer monkeypatched.
# ---------------------------------------------------------------------------

import json

import pytest

from switchboard import claude_scopes, sync_cmd

STDIO = {"type": "stdio", "command": "uvx.exe", "args": ["markitdown-mcp"]}
HTTP = {"type": "http", "url": "http://127.0.0.1:27124/mcp",
        "headers": {"Authorization": "Bearer supersecrettoken"}}


@pytest.fixture
def scopes(tmp_path, monkeypatch):
    """Redirect every claude_scopes path into tmp_path; return writer helpers."""
    src = tmp_path / "home" / ".claude.json"
    cfg = tmp_path / "home" / ".claude"
    cfg.mkdir(parents=True)
    monkeypatch.setattr(claude_scopes, "SOURCE_STATE", src)
    monkeypatch.setattr(claude_scopes, "TARGET_CONFIG_DIR", cfg)
    monkeypatch.setattr(claude_scopes, "TARGET_STATE", cfg / ".claude.json")
    monkeypatch.setattr(claude_scopes, "SETTINGS_PATH", cfg / "settings.json")
    monkeypatch.setattr(claude_scopes, "LEGACY_CCR_CONFIG", tmp_path / "home" / ".ccr" / "config.json")
    monkeypatch.setattr(claude_scopes, "MANIFEST_PATH", cfg / ".switchboard-sync-manifest.json")

    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    return write


class TestAuditMode:
    """cmd_sync() without flags: read-only audit."""

    def test_drift_prints_report_and_exits_1(self, scopes, capsys):
        """Missing servers show as DRIFT lines and exit code is 1."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"markitdown": STDIO}})
        scopes(claude_scopes.TARGET_STATE, {})
        with pytest.raises(SystemExit) as exc:
            sync_cmd.cmd_sync([])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "markitdown" in out and "missing" in out
        assert "--apply" in out  # tells the user how to fix

    def test_in_sync_exits_cleanly(self, scopes, capsys):
        """No drift -> no SystemExit, report says in sync."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"markitdown": STDIO}})
        scopes(claude_scopes.TARGET_STATE, {"mcpServers": {"markitdown": dict(STDIO)}})
        sync_cmd.cmd_sync([])
        assert "in sync" in capsys.readouterr().out

    def test_secret_values_never_printed(self, scopes, capsys):
        """Header token from an http server must not appear in any output."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"obsidian": HTTP}})
        scopes(claude_scopes.TARGET_STATE, {})
        with pytest.raises(SystemExit):
            sync_cmd.cmd_sync([])
        assert "supersecrettoken" not in capsys.readouterr().out

    def test_warns_for_ccr_managed_settings_and_legacy_config(self, scopes, capsys):
        """ISS-002/ISS-003 conditions surface as WARN lines in the audit."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {}})
        scopes(claude_scopes.TARGET_STATE, {"mcpServers": {}})
        scopes(claude_scopes.SETTINGS_PATH,
               {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3456"}})
        scopes(claude_scopes.LEGACY_CCR_CONFIG, {"Providers": [{"api_key": "sk-x"}]})
        sync_cmd.cmd_sync([])
        out = capsys.readouterr().out
        assert "[WARN]" in out and "inert" in out and "sk-x" not in out

    def test_output_is_pure_ascii_for_cp1252_consoles(self, scopes, capsys):
        """The plugin command runs bare python on Windows (cp1252 stdout):
        every printed character must be ASCII or the report crashes."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"markitdown": STDIO, "obsidian": HTTP}})
        scopes(claude_scopes.TARGET_STATE, {"mcpServers": {"markitdown": dict(STDIO)}})
        scopes(claude_scopes.SETTINGS_PATH,
               {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:3456"}})
        with pytest.raises(SystemExit):
            sync_cmd.cmd_sync([])
        out = capsys.readouterr().out
        assert out.isascii(), f"non-ascii chars in output: {[c for c in out if not c.isascii()]}"

    def test_malformed_source_exits_2(self, scopes, capsys):
        """Unreadable source state file is a hard error (exit 2)."""
        claude_scopes.SOURCE_STATE.parent.mkdir(parents=True, exist_ok=True)
        claude_scopes.SOURCE_STATE.write_text("{broken", encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            sync_cmd.cmd_sync([])
        assert exc.value.code == 2


class TestApplyMode:
    """cmd_sync(['--apply'])."""

    def test_apply_invokes_apply_plan_and_saves_manifest(self, scopes, monkeypatch, capsys):
        """--apply routes through sync_apply and persists the returned manifest."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"markitdown": STDIO}})
        scopes(claude_scopes.TARGET_STATE, {})
        recorded = {}
        def fake_apply(plan, source, manifest, prune=False, run=None):
            recorded["plan"] = plan
            recorded["prune"] = prune
            return ([sync_cmd.sync_apply.ApplyResult("markitdown", "add", True, "added")],
                    {"markitdown": "fp"})
        monkeypatch.setattr(sync_cmd.sync_apply, "apply_plan", fake_apply)
        saved = {}
        monkeypatch.setattr(sync_cmd.sync_apply, "save_manifest",
                            lambda m: saved.update(m))
        sync_cmd.cmd_sync(["--apply"])
        assert recorded["plan"].adds == ("markitdown",)
        assert recorded["prune"] is False
        assert saved == {"markitdown": "fp"}
        out = capsys.readouterr().out
        assert "NEXT" in out or "next" in out  # explains when servers appear

    def test_apply_when_in_sync_is_a_noop(self, scopes, monkeypatch, capsys):
        """Idempotence: no drift -> apply_plan never called, exit clean."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"a": STDIO}})
        scopes(claude_scopes.TARGET_STATE, {"mcpServers": {"a": dict(STDIO)}})
        def explode(*a, **k):
            raise AssertionError("apply_plan must not be called when in sync")
        monkeypatch.setattr(sync_cmd.sync_apply, "apply_plan", explode)
        sync_cmd.cmd_sync(["--apply"])
        assert "already in sync" in capsys.readouterr().out.lower()

    def test_apply_failure_exits_2(self, scopes, monkeypatch, capsys):
        """Any failed server result makes apply exit 2."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"a": STDIO}})
        scopes(claude_scopes.TARGET_STATE, {})
        monkeypatch.setattr(
            sync_cmd.sync_apply, "apply_plan",
            lambda plan, source, manifest, prune=False, run=None:
                ([sync_cmd.sync_apply.ApplyResult("a", "add", False, "boom")], dict(manifest)))
        monkeypatch.setattr(sync_cmd.sync_apply, "save_manifest", lambda m: None)
        with pytest.raises(SystemExit) as exc:
            sync_cmd.cmd_sync(["--apply"])
        assert exc.value.code == 2

    def test_missing_claude_exe_exits_2_before_any_write(self, scopes, monkeypatch, capsys):
        """No claude executable -> actionable error, exit 2, nothing applied."""
        scopes(claude_scopes.SOURCE_STATE, {"mcpServers": {"a": STDIO}})
        scopes(claude_scopes.TARGET_STATE, {})
        monkeypatch.setattr(sync_cmd.sync_apply, "claude_exe", lambda: None)
        with pytest.raises(SystemExit) as exc:
            sync_cmd.cmd_sync(["--apply"])
        assert exc.value.code == 2
        assert "claude" in capsys.readouterr().out.lower()
