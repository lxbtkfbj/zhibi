"""分段确认是独立开关：旧书默认为开，不改变力度，也不拼入提示词。"""

from types import SimpleNamespace

import pytest

from app.book_settings import BookSettings, compile_rules, default_settings, merge_settings, settings_of


def test_segment_approval_defaults_for_new_and_legacy_books():
    assert BookSettings().segment_approval is True
    assert default_settings()["segment_approval"] is True
    for settings in (None, {}, {"volume_approval": False}):
        assert settings_of(SimpleNamespace(settings=settings))["segment_approval"] is True
    assert settings_of(SimpleNamespace(settings={"segment_approval": False}))["segment_approval"] is False


@pytest.mark.parametrize("preset", ["quick", "balanced", "premium", "custom"])
@pytest.mark.parametrize("enabled", [True, False])
def test_segment_approval_independent_of_effort_preset(preset, enabled):
    result = merge_settings({"segment_approval": enabled}, {"effort_preset": preset})
    assert result["segment_approval"] is enabled
    toggled = merge_settings(result, {"segment_approval": not enabled})
    assert toggled == {**result, "segment_approval": not enabled}
    assert compile_rules(result) == compile_rules(toggled)
    assert compile_rules({"segment_approval": enabled}) == ""
