"""Tracking-mode policy kept independent from ROS for regression tests."""


def normalize_tracking_mode(value):
    mode = str(value or "").strip().lower()
    if mode not in ("selected", "automatic"):
        raise ValueError("tracking_mode must be 'selected' or 'automatic'")
    return mode


def selection_policy(mode, selected_id, compatibility_auto=False):
    mode = normalize_tracking_mode(mode)
    if mode == "automatic":
        # Official MOT assigns its own IDs. Never compare them with the Luka
        # selected-mode tracker IDs.
        return None, True
    return selected_id, bool(compatibility_auto)
