# test_mcp_sync.py - Tests for the pure MCP diff engine (normalize/fingerprint/plan/redact).
#
# Everything here is pure: dicts in, dataclasses out. No I/O of any kind.
# ---------------------------------------------------------------------------

from switchboard import mcp_sync


STDIO = {"type": "stdio", "command": "uvx.exe", "args": ["markitdown-mcp"], "env": {}}
HTTP = {"type": "http", "url": "http://127.0.0.1:27124/mcp", "headers": {"Authorization": "Bearer tok123"}}


# ---------------------------------------------------------------------------
# normalize / fingerprint
# ---------------------------------------------------------------------------


class TestNormalize:
    """Tests for normalize()."""

    def test_drops_empty_collections_and_nones(self):
        """Empty env/args/None values are dropped so cosmetic diffs don't count."""
        out = mcp_sync.normalize({"command": "x", "env": {}, "args": [], "cwd": None})
        assert out == {"command": "x"}

    def test_keeps_meaningful_values(self):
        """Non-empty fields survive normalization unchanged."""
        out = mcp_sync.normalize(STDIO)
        assert out == {"type": "stdio", "command": "uvx.exe", "args": ["markitdown-mcp"]}


class TestFingerprint:
    """Tests for fingerprint()."""

    def test_stable_across_key_order(self):
        """Same definition in different key order fingerprints identically."""
        a = {"command": "x", "args": ["1"], "type": "stdio"}
        b = {"type": "stdio", "args": ["1"], "command": "x"}
        assert mcp_sync.fingerprint(a) == mcp_sync.fingerprint(b)

    def test_differs_for_different_definitions(self):
        """A changed arg changes the fingerprint."""
        a = {"command": "x", "args": ["1"]}
        b = {"command": "x", "args": ["2"]}
        assert mcp_sync.fingerprint(a) != mcp_sync.fingerprint(b)

    def test_ignores_empty_env_difference(self):
        """{'env': {}} vs absent env is the same server (normalized equal)."""
        a = {"command": "x", "env": {}}
        b = {"command": "x"}
        assert mcp_sync.fingerprint(a) == mcp_sync.fingerprint(b)


# ---------------------------------------------------------------------------
# redact
# ---------------------------------------------------------------------------


class TestRedact:
    """Tests for redact()."""

    def test_mask_is_ascii_safe_for_cp1252_consoles(self):
        """The mask must survive Windows cp1252 stdout (bare-python plugin path)."""
        assert mcp_sync.MASK.isascii()

    def test_masks_header_values(self):
        """Header values are masked; header names survive."""
        out = mcp_sync.redact(HTTP)
        assert out["headers"]["Authorization"] == mcp_sync.MASK
        assert "tok123" not in str(out)

    def test_masks_env_values(self):
        """Env var values are masked; names survive."""
        out = mcp_sync.redact({"command": "x", "env": {"API_TOKEN": "sekrit"}})
        assert out["env"]["API_TOKEN"] == mcp_sync.MASK
        assert "sekrit" not in str(out)

    def test_masks_keylike_top_level_fields(self):
        """Fields whose name smells like a secret (key/token/secret) are masked."""
        out = mcp_sync.redact({"url": "http://x", "apiKey": "abc"})
        assert out["apiKey"] == mcp_sync.MASK
        assert out["url"] == "http://x"

    def test_does_not_mutate_input(self):
        """redact returns a new dict; the original is untouched (immutability)."""
        src = {"command": "x", "env": {"A": "v"}}
        mcp_sync.redact(src)
        assert src["env"]["A"] == "v"


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


class TestBuildPlan:
    """Tests for build_plan(source, target, manifest)."""

    def test_all_missing_when_target_empty(self):
        """Every source server is an add when the target scope is empty."""
        plan = mcp_sync.build_plan({"a": STDIO, "b": HTTP}, {}, {})
        assert sorted(plan.adds) == ["a", "b"]
        assert plan.updates == ()
        assert plan.in_sync == ()

    def test_in_sync_when_definitions_match(self):
        """Identical (normalized) definitions classify as in_sync."""
        plan = mcp_sync.build_plan({"a": STDIO}, {"a": dict(STDIO)}, {})
        assert plan.in_sync == ("a",)
        assert plan.adds == () and plan.updates == ()

    def test_update_when_definition_drifts(self):
        """Same name with a different definition classifies as an update."""
        changed = {**STDIO, "args": ["other-mcp"]}
        plan = mcp_sync.build_plan({"a": STDIO}, {"a": changed}, {})
        assert plan.updates == ("a",)

    def test_orphan_managed_when_manifest_fingerprint_matches(self):
        """A target-only server that switchboard added (manifest match) is prunable."""
        manifest = {"gone": mcp_sync.fingerprint(STDIO)}
        plan = mcp_sync.build_plan({}, {"gone": dict(STDIO)}, manifest)
        assert plan.orphans_managed == ("gone",)
        assert plan.orphans_foreign == ()

    def test_orphan_foreign_when_not_in_manifest(self):
        """A target-only server the user added themselves is never prunable."""
        plan = mcp_sync.build_plan({}, {"users-own": STDIO}, {})
        assert plan.orphans_foreign == ("users-own",)
        assert plan.orphans_managed == ()

    def test_orphan_foreign_when_manifest_fingerprint_mismatches(self):
        """Manifest entry with a stale fingerprint means the user changed it: foreign."""
        manifest = {"gone": "not-the-current-fingerprint"}
        plan = mcp_sync.build_plan({}, {"gone": STDIO}, manifest)
        assert plan.orphans_foreign == ("gone",)

    def test_has_drift_reflects_actionable_categories(self):
        """has_drift is True for adds/updates/managed orphans, False when clean."""
        drifted = mcp_sync.build_plan({"a": STDIO}, {}, {})
        clean = mcp_sync.build_plan({"a": STDIO}, {"a": dict(STDIO)}, {})
        assert drifted.has_drift is True
        assert clean.has_drift is False

    def test_foreign_orphans_alone_do_not_count_as_drift(self):
        """User-added CCR-scope servers must not force exit-code drift."""
        plan = mcp_sync.build_plan({}, {"users-own": STDIO}, {})
        assert plan.has_drift is False
