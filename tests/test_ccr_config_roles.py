# test_ccr_config_roles.py - Tests for set_all_roles, set_websearch_online, ensure_apikey_blank.
#
# All tests are hermetic -- no real file I/O, no real CCR process, no real network.
# ---------------------------------------------------------------------------

from switchboard import ccr_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_with_router(**extra_router_keys) -> dict:
    """Return a minimal cfg dict with a Router section plus optional extra keys."""
    router = {
        "default": "openrouter,deepseek/deepseek-chat",
        "background": "openrouter,deepseek/deepseek-chat",
        "think": "openrouter,deepseek/deepseek-r1",
        "longContext": "openrouter,deepseek/deepseek-chat",
        "webSearch": "openrouter,deepseek/deepseek-chat",
        "longContextThreshold": 200000,
        "image": "",
    }
    router.update(extra_router_keys)
    return {
        "LOG": False,
        "HOST": "127.0.0.1",
        "PORT": 3456,
        "APIKEY": "old-key",
        "Providers": [{"name": "openrouter", "api_key": "SECRET"}],
        "Router": router,
    }


# ---------------------------------------------------------------------------
# set_all_roles
# ---------------------------------------------------------------------------


class TestSetAllRoles:
    """Tests for set_all_roles()."""

    MODEL = "anthropic/claude-3-5-sonnet"

    def test_sets_all_five_roles(self):
        """Every role in ROLES is set to openrouter,<model>."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        for role in ccr_config.ROLES:
            assert result["Router"][role] == f"openrouter,{self.MODEL}"

    def test_websearch_no_online_when_online_false(self):
        """With online=False, webSearch must NOT end with ':online'."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL, online=False)
        assert result["Router"]["webSearch"] == f"openrouter,{self.MODEL}"
        assert not result["Router"]["webSearch"].endswith(":online")

    def test_websearch_online_suffix_when_online_true(self):
        """With online=True, webSearch must end with ':online'."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL, online=True)
        assert result["Router"]["webSearch"] == f"openrouter,{self.MODEL}:online"

    def test_other_roles_not_online_when_online_true(self):
        """With online=True, only webSearch gets ':online'; all other roles do not."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL, online=True)
        for role in ccr_config.ROLES:
            if role == "webSearch":
                continue
            assert not result["Router"][role].endswith(":online"), (
                f"Role '{role}' should not end with ':online'"
            )

    def test_preserves_longcontext_threshold(self):
        """longContextThreshold in Router must survive the update."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["Router"]["longContextThreshold"] == 200000

    def test_preserves_image_key(self):
        """image key in Router must survive the update."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["Router"]["image"] == ""

    def test_preserves_arbitrary_router_key(self):
        """Unrecognised Router keys are left intact."""
        cfg = _cfg_with_router(customKey="custom-value")
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["Router"]["customKey"] == "custom-value"

    def test_does_not_mutate_input(self):
        """Input cfg must not be modified in place."""
        cfg = _cfg_with_router()
        original_router = dict(cfg["Router"])
        ccr_config.set_all_roles(cfg, self.MODEL)
        assert cfg["Router"] == original_router

    def test_does_not_touch_top_level_keys(self):
        """Top-level keys (LOG, HOST, PORT, APIKEY, Providers) are untouched."""
        cfg = _cfg_with_router()
        result = ccr_config.set_all_roles(cfg, self.MODEL)
        assert result["LOG"] == cfg["LOG"]
        assert result["HOST"] == cfg["HOST"]
        assert result["PORT"] == cfg["PORT"]
        assert result["APIKEY"] == cfg["APIKEY"]
        assert result["Providers"] is cfg["Providers"]


# ---------------------------------------------------------------------------
# set_websearch_online
# ---------------------------------------------------------------------------


class TestSetWebsearchOnline:
    """Tests for set_websearch_online()."""

    BASE_VALUE = "openrouter,deepseek/deepseek-chat"

    def _cfg(self) -> dict:
        """Return cfg with a plain webSearch (no :online)."""
        cfg = _cfg_with_router()
        cfg["Router"]["webSearch"] = self.BASE_VALUE
        return cfg

    def test_adds_online_suffix_when_true(self):
        """on=True appends ':online' to the existing webSearch value."""
        cfg = self._cfg()
        result = ccr_config.set_websearch_online(cfg, on=True)
        assert result["Router"]["webSearch"] == f"{self.BASE_VALUE}:online"

    def test_removes_online_suffix_when_false(self):
        """on=False strips ':online' from the webSearch value."""
        cfg = _cfg_with_router()
        cfg["Router"]["webSearch"] = f"{self.BASE_VALUE}:online"
        result = ccr_config.set_websearch_online(cfg, on=False)
        assert result["Router"]["webSearch"] == self.BASE_VALUE

    def test_round_trips(self):
        """on=True then on=False returns to the original base value."""
        cfg = self._cfg()
        enabled = ccr_config.set_websearch_online(cfg, on=True)
        restored = ccr_config.set_websearch_online(enabled, on=False)
        assert restored["Router"]["webSearch"] == self.BASE_VALUE

    def test_idempotent_true(self):
        """Calling on=True twice does not double-append ':online'."""
        cfg = self._cfg()
        once = ccr_config.set_websearch_online(cfg, on=True)
        twice = ccr_config.set_websearch_online(once, on=True)
        assert twice["Router"]["webSearch"] == f"{self.BASE_VALUE}:online"

    def test_idempotent_false(self):
        """Calling on=False when already plain does not corrupt the value."""
        cfg = self._cfg()
        result = ccr_config.set_websearch_online(cfg, on=False)
        assert result["Router"]["webSearch"] == self.BASE_VALUE

    def test_does_not_mutate_input(self):
        """Input cfg must not be modified in place."""
        cfg = self._cfg()
        original_ws = cfg["Router"]["webSearch"]
        ccr_config.set_websearch_online(cfg, on=True)
        assert cfg["Router"]["webSearch"] == original_ws

    def test_preserves_other_router_keys(self):
        """Other Router keys (longContextThreshold, etc.) are untouched."""
        cfg = self._cfg()
        result = ccr_config.set_websearch_online(cfg, on=True)
        assert result["Router"]["longContextThreshold"] == 200000


