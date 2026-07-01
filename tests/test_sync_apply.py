# test_sync_apply.py - Tests for the side-effect layer: claude-exe resolution,
# add-json/remove invocation, and the sync manifest.
#
# All subprocess activity is captured by a fake runner; no real claude is run.
# ---------------------------------------------------------------------------

import json
from types import SimpleNamespace

from switchboard import claude_scopes, mcp_sync, sync_apply

STDIO = {"type": "stdio", "command": "uvx.exe", "args": ["markitdown-mcp"]}


def ok_runner(calls):
    """Fake subprocess.run that records argv+env and always succeeds."""
    def run(argv, env=None, capture_output=None, text=None, check=None):
        calls.append({"argv": argv, "env": env})
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    return run


# ---------------------------------------------------------------------------
# claude_exe
# ---------------------------------------------------------------------------


class TestClaudeExe:
    """Tests for claude_exe()."""

    def test_uses_which_when_available(self, monkeypatch):
        """Resolves via shutil.which first."""
        monkeypatch.setattr(sync_apply.shutil, "which", lambda name: r"C:\bin\claude.exe")
        assert sync_apply.claude_exe() == r"C:\bin\claude.exe"

    def test_falls_back_to_local_bin(self, monkeypatch, tmp_path):
        """Falls back to ~/.local/bin/claude.exe when which finds nothing."""
        exe = tmp_path / ".local" / "bin" / "claude.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("stub")
        monkeypatch.setattr(sync_apply.shutil, "which", lambda name: None)
        monkeypatch.setattr(sync_apply.Path, "home", classmethod(lambda cls: tmp_path))
        assert sync_apply.claude_exe() == str(exe)

    def test_returns_none_when_not_found_anywhere(self, monkeypatch, tmp_path):
        """Returns None (caller decides how to error) when claude is absent."""
        monkeypatch.setattr(sync_apply.shutil, "which", lambda name: None)
        monkeypatch.setattr(sync_apply.Path, "home", classmethod(lambda cls: tmp_path))
        assert sync_apply.claude_exe() is None


# ---------------------------------------------------------------------------
# apply_plan
# ---------------------------------------------------------------------------


class TestApplyPlan:
    """Tests for apply_plan()."""

    def test_add_invokes_add_json_with_config_dir_env(self, monkeypatch):
        """An add runs `claude mcp add-json <name> <json> --scope user` with
        CLAUDE_CONFIG_DIR pointing at the CCR target scope."""
        calls = []
        monkeypatch.setattr(sync_apply, "claude_exe", lambda: "claude.exe")
        plan = mcp_sync.build_plan({"a": STDIO}, {}, {})
        results, manifest = sync_apply.apply_plan(
            plan, {"a": STDIO}, {}, run=ok_runner(calls))
        assert len(calls) == 1
        argv = calls[0]["argv"]
        assert argv[:3] == ["claude.exe", "mcp", "add-json"]
        assert argv[3] == "a"
        assert json.loads(argv[4]) == STDIO
        assert argv[5:] == ["--scope", "user"]
        assert calls[0]["env"]["CLAUDE_CONFIG_DIR"] == str(claude_scopes.TARGET_CONFIG_DIR)
        assert results[0].ok is True and results[0].action == "add"

    def test_update_removes_then_readds(self, monkeypatch):
        """An update runs remove first, then add-json (add-json never overwrites)."""
        calls = []
        monkeypatch.setattr(sync_apply, "claude_exe", lambda: "claude.exe")
        old = {**STDIO, "args": ["old"]}
        plan = mcp_sync.build_plan({"a": STDIO}, {"a": old}, {})
        sync_apply.apply_plan(plan, {"a": STDIO}, {}, run=ok_runner(calls))
        assert [c["argv"][2] for c in calls] == ["remove", "add-json"]
        assert calls[0]["argv"][3] == "a"

    def test_prune_removes_managed_orphans_only_when_enabled(self, monkeypatch):
        """Managed orphans are removed only with prune=True."""
        calls = []
        monkeypatch.setattr(sync_apply, "claude_exe", lambda: "claude.exe")
        manifest = {"gone": mcp_sync.fingerprint(STDIO)}
        plan = mcp_sync.build_plan({}, {"gone": STDIO}, manifest)

        sync_apply.apply_plan(plan, {}, manifest, run=ok_runner(calls))
        assert calls == []  # prune defaults off

        results, new_manifest = sync_apply.apply_plan(
            plan, {}, manifest, prune=True, run=ok_runner(calls))
        assert calls[0]["argv"][2:4] == ["remove", "gone"]
        assert "gone" not in new_manifest

    def test_successful_add_records_fingerprint_in_manifest(self, monkeypatch):
        """The returned manifest gains name -> fingerprint for each synced server."""
        monkeypatch.setattr(sync_apply, "claude_exe", lambda: "claude.exe")
        plan = mcp_sync.build_plan({"a": STDIO}, {}, {})
        _, manifest = sync_apply.apply_plan(plan, {"a": STDIO}, {}, run=ok_runner([]))
        assert manifest == {"a": mcp_sync.fingerprint(STDIO)}

    def test_failed_subprocess_reports_failure_and_continues(self, monkeypatch):
        """A failing server is reported ok=False; later servers still run;
        the failed server is NOT recorded in the manifest."""
        monkeypatch.setattr(sync_apply, "claude_exe", lambda: "claude.exe")
        def flaky(argv, env=None, capture_output=None, text=None, check=None):
            code = 1 if argv[3] == "a" else 0
            return SimpleNamespace(returncode=code, stdout="", stderr="boom")
        plan = mcp_sync.build_plan({"a": STDIO, "b": STDIO}, {}, {})
        results, manifest = sync_apply.apply_plan(
            plan, {"a": STDIO, "b": STDIO}, {}, run=flaky)
        by_name = {r.name: r for r in results}
        assert by_name["a"].ok is False and "boom" in by_name["a"].detail
        assert by_name["b"].ok is True
        assert "a" not in manifest and "b" in manifest

    def test_input_manifest_never_mutated(self, monkeypatch):
        """apply_plan returns a NEW manifest dict (immutability rule)."""
        monkeypatch.setattr(sync_apply, "claude_exe", lambda: "claude.exe")
        original: dict = {}
        plan = mcp_sync.build_plan({"a": STDIO}, {}, original)
        sync_apply.apply_plan(plan, {"a": STDIO}, original, run=ok_runner([]))
        assert original == {}


# ---------------------------------------------------------------------------
# Manifest I/O
# ---------------------------------------------------------------------------


class TestManifestIO:
    """Tests for load_manifest / save_manifest."""

    def test_load_returns_empty_when_missing(self, tmp_path, monkeypatch):
        """No manifest file yet -> {}."""
        monkeypatch.setattr(claude_scopes, "MANIFEST_PATH", tmp_path / "m.json")
        assert sync_apply.load_manifest() == {}

    def test_round_trip(self, tmp_path, monkeypatch):
        """save_manifest then load_manifest round-trips the mapping."""
        monkeypatch.setattr(claude_scopes, "MANIFEST_PATH", tmp_path / "m.json")
        sync_apply.save_manifest({"a": "f1"})
        assert sync_apply.load_manifest() == {"a": "f1"}

    def test_save_is_atomic_no_partial_file_on_disk(self, tmp_path, monkeypatch):
        """save writes via temp+replace: the final path is valid JSON afterwards."""
        target = tmp_path / "m.json"
        monkeypatch.setattr(claude_scopes, "MANIFEST_PATH", target)
        sync_apply.save_manifest({"a": "f1"})
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data["synced"] == {"a": "f1"}
        assert data["version"] == 1
