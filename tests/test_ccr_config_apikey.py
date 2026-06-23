# test_ccr_config_apikey.py - Tests for ensure_apikey_blank.
#
# All tests are hermetic -- no real file I/O, no real CCR process.
# ---------------------------------------------------------------------------

from switchboard import ccr_config


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
# ensure_apikey_blank
# ---------------------------------------------------------------------------


class TestEnsureApikeyBlank:
    """Tests for ensure_apikey_blank()."""

    def test_sets_apikey_to_empty_string(self):
        """APIKEY must be set to '' regardless of its previous value."""
        cfg = _cfg_with_router()
        cfg["APIKEY"] = "some-old-key"
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["APIKEY"] == ""

    def test_already_blank_stays_blank(self):
        """If APIKEY is already blank, result must still be ''."""
        cfg = _cfg_with_router()
        cfg["APIKEY"] = ""
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["APIKEY"] == ""

    def test_leaves_providers_untouched(self):
        """Providers list must not be modified (secret api_key inside)."""
        cfg = _cfg_with_router()
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["Providers"] is cfg["Providers"]

    def test_leaves_other_keys_untouched(self):
        """Non-APIKEY top-level keys must survive."""
        cfg = _cfg_with_router()
        result = ccr_config.ensure_apikey_blank(cfg)
        assert result["HOST"] == cfg["HOST"]
        assert result["PORT"] == cfg["PORT"]
        assert result["Router"] == cfg["Router"]

    def test_does_not_mutate_input(self):
        """Input cfg must not be modified in place."""
        cfg = _cfg_with_router()
        cfg["APIKEY"] = "secret"
        ccr_config.ensure_apikey_blank(cfg)
        assert cfg["APIKEY"] == "secret"
