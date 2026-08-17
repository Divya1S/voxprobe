"""The dial guard is the one piece of code where a bug can dial a stranger — test it first."""

import pytest

from voxprobe.config import TargetNumberError, assert_allowed_target, load_settings, normalize_e164, parse_allowlist

ALLOWED = parse_allowlist("+15550101234, +1 (555) 010-9999")


@pytest.mark.parametrize(
    "raw", ["+15550101234", "+1 (555) 010-1234", "1-555-010-1234", "15550101234", " +1 555 010 1234 "]
)
def test_guard_accepts_every_spelling_of_an_allowed_number(raw):
    assert assert_allowed_target(raw, ALLOWED) == "+15550101234"


@pytest.mark.parametrize("raw", ["+15550101235", "+18005551212", "911", "+442071234567"])
def test_guard_refuses_numbers_not_on_the_allowlist(raw):
    with pytest.raises((TargetNumberError, ValueError)):
        assert_allowed_target(raw, ALLOWED)


def test_empty_allowlist_refuses_everything():
    with pytest.raises(TargetNumberError):
        assert_allowed_target("+15550101234", frozenset())


def test_normalize_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_e164("call me maybe")


def test_settings_load_without_any_phone_adapter(monkeypatch):
    for k in ("VAPI_API_KEY", "VAPI_PHONE_NUMBER_ID", "ALLOWED_NUMBERS_E164"):
        monkeypatch.delenv(k, raising=False)
    settings = load_settings()
    assert settings.recordings_dir.name == "recordings"
    assert settings.allowed_numbers == frozenset() or isinstance(settings.allowed_numbers, frozenset)
