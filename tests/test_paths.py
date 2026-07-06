# test_paths.py - Switchboard home dir + translator runtime path derivation.
#
# Hermetic: every path is derived from a root the test controls (tmp_path); no
# real ~/.switchboard is ever created.

from pathlib import Path

from switchboard import paths


class TestHomeDir:
    """Tests for home_dir(root)."""

    def test_default_under_user_home(self):
        """With no root, the home dir sits under the user's home directory."""
        assert paths.home_dir() == Path.home() / paths.APP_DIRNAME

    def test_root_override_redirects_whole_tree(self, tmp_path):
        """Passing root relocates the home dir (tests redirect the tree here)."""
        assert paths.home_dir(tmp_path) == tmp_path / paths.APP_DIRNAME


class TestDerivedPaths:
    """Tests for the engine/config/pid/log path helpers."""

    def test_all_paths_sit_under_home(self, tmp_path):
        """Every runtime path is a direct child of the switchboard home dir."""
        home = paths.home_dir(tmp_path)
        assert paths.engine_dir(tmp_path).parent == home
        assert paths.proxy_config_path(tmp_path).parent == home
        assert paths.proxy_pidfile(tmp_path).parent == home
        assert paths.proxy_logfile(tmp_path).parent == home

    def test_names_are_stable(self, tmp_path):
        """The on-disk names are the ones the rest of the system expects."""
        assert paths.engine_dir(tmp_path).name == "engine"
        assert paths.proxy_config_path(tmp_path).name == "proxy.yaml"
        assert paths.proxy_pidfile(tmp_path).name == "proxy.pid"
        assert paths.proxy_logfile(tmp_path).name == "proxy.log"
