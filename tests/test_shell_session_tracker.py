from dhara.shell.session_tracker import DharaSessionTracker, DruvaSessionTracker


def test_session_tracker_uses_default_component_name():
    tracker = DharaSessionTracker()

    assert tracker.component_name == "dhara"
    assert tracker.session_buddy_path.endswith("session-buddy")


def test_session_tracker_accepts_custom_component_name_and_alias():
    tracker = DruvaSessionTracker(component_name="custom")

    assert isinstance(tracker, DharaSessionTracker)
    assert tracker.component_name == "custom"
    assert DruvaSessionTracker is DharaSessionTracker
