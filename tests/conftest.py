"""Shared fixtures."""
import pytest

from pipeline import keys, switch


@pytest.fixture(autouse=True)
def switch_without_asking(monkeypatch):
    """Chains move to the next service as before; tests of the question turn this off."""
    monkeypatch.setattr(switch, "AUTO", True)
    switch.new_run()


@pytest.fixture
def no_keys(tmp_path, monkeypatch):
    """Blank every API key variable and point .env at a scratch file, so a test neither
    sees the real keys nor leaves one behind (monkeypatch restores each variable)."""
    for spec in keys.SERVICES.values():
        for field in spec["fields"]:
            for slot in range(1, 21):
                monkeypatch.setenv(keys._name(field, slot), "")
        for alias in spec.get("aliases", {}).values():
            monkeypatch.setenv(alias, "")
    for name in [*keys.SERVICES, *keys.PURPOSES]:  # which key each purpose starts with
        monkeypatch.setenv(keys._pref_name(name), "")
    monkeypatch.setattr(keys, "_env_path", lambda: tmp_path / ".env")
    keys._ACTIVE.clear()
    keys._OUT.clear()
    yield
    keys._ACTIVE.clear()
    keys._OUT.clear()
