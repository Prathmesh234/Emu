"""
tests/test_action_validator.py

Unit tests for context_manager/action_validator.py.

Run from backend/ directory:
    python -m pytest tests/test_action_validator.py -v
"""
import sys
import os

# Ensure backend/ is on the path so we can import the module directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from context_manager.action_validator import ActionValidator

SESSION = "test-session"


def make_move(x=0.5, y=0.5):
    return {"type": "mouse_move", "coordinates": {"x": x, "y": y}}


def make_click(kind="left_click"):
    return {"type": kind}


def make_scroll(direction="down", amount=5):
    return {"type": "scroll", "direction": direction, "amount": amount}


# ── Rule 1: No consecutive mouse_moves ────────────────────────────────────────

class TestRule1_NoConsecutiveMouseMoves:
    def test_single_move_allowed(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(0.5, 0.5))
        assert ok, msg

    def test_two_consecutive_moves_rejected(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.5, 0.5))
        ok, msg = av.validate(SESSION, make_move(0.6, 0.6))
        assert not ok
        assert "Cannot move twice" in msg

    def test_move_then_click_then_move_allowed(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.5, 0.5))
        av.validate(SESSION, make_click())
        ok, msg = av.validate(SESSION, make_move(0.7, 0.7))
        assert ok, msg

    def test_move_then_type_then_move_allowed(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.3, 0.3))
        av.validate(SESSION, {"type": "type_text", "text": "hello"})
        ok, msg = av.validate(SESSION, make_move(0.8, 0.8))
        assert ok, msg


# ── Rule 2: Micro-movement (same coordinates) ─────────────────────────────────

class TestRule2_MicroMovement:
    def test_same_exact_coords_rejected(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.5, 0.5))
        av.validate(SESSION, make_click())           # click in between
        ok, msg = av.validate(SESSION, make_move(0.5, 0.5))
        assert not ok
        assert "already at" in msg or "no-op" in msg

    def test_within_epsilon_rejected(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.5, 0.5))
        av.validate(SESSION, make_click())
        # 0.005 < epsilon (0.01) → same spot
        ok, msg = av.validate(SESSION, make_move(0.505, 0.505))
        assert not ok

    def test_outside_epsilon_allowed(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.5, 0.5))
        av.validate(SESSION, make_click())
        # 0.02 > epsilon (0.01) → different spot
        ok, msg = av.validate(SESSION, make_move(0.52, 0.52))
        assert ok, msg

    def test_first_move_never_micro(self):
        """No previous move → micro-movement check is skipped."""
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(0.5, 0.5))
        assert ok, msg


# ── Rule 3: Same action 5+ consecutive times ──────────────────────────────────

class TestRule3_ConsecutiveActions:
    def test_four_identical_clicks_allowed(self):
        av = ActionValidator()
        for _ in range(4):
            ok, msg = av.validate(SESSION, make_click())
        assert ok, msg  # 4th should still be allowed

    def test_fifth_identical_click_rejected(self):
        av = ActionValidator()
        for _ in range(4):
            av.validate(SESSION, make_click())
        ok, msg = av.validate(SESSION, make_click())
        assert not ok
        assert "left_click" in msg
        assert "5 times" in msg

    def test_four_type_text_allowed(self):
        av = ActionValidator()
        for _ in range(4):
            ok, _ = av.validate(SESSION, {"type": "type_text", "text": "a"})
        assert ok

    def test_fifth_type_text_rejected(self):
        av = ActionValidator()
        for _ in range(4):
            av.validate(SESSION, {"type": "type_text", "text": "a"})
        ok, msg = av.validate(SESSION, {"type": "type_text", "text": "a"})
        assert not ok
        assert "type_text" in msg

    def test_interleaved_actions_reset_counter(self):
        """A different action in the middle should reset the consecutive count."""
        av = ActionValidator()
        for _ in range(3):
            av.validate(SESSION, make_click())
        # Different action breaks the streak
        av.validate(SESSION, make_move(0.5, 0.5))
        av.validate(SESSION, make_click())          # count resets: this is only "1st" in new streak
        ok, _ = av.validate(SESSION, make_click())  # 2nd consecutive → allowed
        assert ok

    def test_screenshots_not_throttled(self):
        """screenshot is in _NO_THROTTLE — should never be blocked."""
        av = ActionValidator()
        for _ in range(10):
            ok, msg = av.validate(SESSION, {"type": "screenshot"})
        assert ok, msg

    def test_scroll_not_throttled(self):
        """scroll is in _NO_THROTTLE — should never be blocked."""
        av = ActionValidator()
        for _ in range(10):
            ok, msg = av.validate(SESSION, make_scroll())
        assert ok, msg

    def test_different_click_types_independent(self):
        """left_click and right_click are counted separately."""
        av = ActionValidator()
        for _ in range(4):
            av.validate(SESSION, make_click("left_click"))
        # Switching to right_click should reset the left_click streak
        ok, msg = av.validate(SESSION, make_click("right_click"))
        assert ok, msg


# ── Rule 4: Minimum scroll amount ─────────────────────────────────────────────

class TestRule4_ScrollAmount:
    def test_scroll_amount_5_allowed(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_scroll(amount=5))
        assert ok, msg

    def test_scroll_amount_10_allowed(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_scroll(amount=10))
        assert ok, msg

    def test_scroll_amount_4_rejected(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_scroll(amount=4))
        assert not ok
        assert "5" in msg

    def test_scroll_amount_1_rejected(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_scroll(amount=1))
        assert not ok

    def test_scroll_no_amount_allowed(self):
        """Missing amount field should not trigger the rule."""
        av = ActionValidator()
        ok, msg = av.validate(SESSION, {"type": "scroll", "direction": "down"})
        assert ok, msg


# ── Rule 5: Unknown / plain-text action ───────────────────────────────────────

class TestRule5_UnknownAction:
    def test_unknown_type_rejected(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, {"type": "unknown"})
        assert not ok
        assert "JSON" in msg or "json" in msg

    def test_valid_types_not_rejected(self):
        av = ActionValidator()
        for action_type in ("left_click", "right_click", "double_click",
                            "mouse_move", "type_text", "key_press",
                            "shell_exec", "screenshot", "wait", "done"):
            av.clear(SESSION)
            action = {"type": action_type}
            if action_type == "mouse_move":
                action["coordinates"] = {"x": 0.1, "y": 0.1}
            ok, msg = av.validate(SESSION, action)
            # Only check it's not rejected for the unknown reason
            if not ok:
                assert "Unknown" not in msg, f"{action_type} failed for wrong reason: {msg}"


# ── Rule 6: Absolute coordinate detection ────────────────────────────────────

class TestRule6_AbsoluteCoords:
    def test_normalized_coords_allowed(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(0.45, 0.32))
        assert ok, msg

    def test_boundary_1_0_allowed(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(1.0, 1.0))
        assert ok, msg

    def test_slightly_over_1_allowed(self):
        """Values just above 1.0 (e.g. 1.1) may be rounding — allow."""
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(1.1, 0.9))
        assert ok, msg

    def test_absolute_x_pixel_rejected(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(960, 540))
        assert not ok
        assert "pixel" in msg.lower() or "normalize" in msg.lower() or "norm" in msg.lower()

    def test_large_y_rejected(self):
        av = ActionValidator()
        ok, msg = av.validate(SESSION, make_move(0.5, 1080))
        assert not ok

    def test_absolute_coords_only_for_mouse_move(self):
        """Absolute coordinate check only fires for mouse_move, not other actions."""
        av = ActionValidator()
        # drag with large coordinates — not a mouse_move, should not trigger rule 6
        ok, msg = av.validate(SESSION, {
            "type": "drag",
            "coordinates": {"x": 960, "y": 540},
            "end_coordinates": {"x": 1200, "y": 700},
        })
        # Rule 6 doesn't apply to drag; it may fail for other reasons but not coords
        # (in practice drag is just recorded fine since the rule only checks mouse_move)
        # Just ensure the error isn't about absolute pixels
        if not ok:
            assert "pixel" not in msg.lower()


# ── Session isolation ─────────────────────────────────────────────────────────

class TestSessionIsolation:
    def test_different_sessions_independent(self):
        av = ActionValidator()
        # Fill up session A with 4 clicks
        for _ in range(4):
            av.validate("session-A", make_click())
        # Session B should start fresh — first click is fine
        ok, msg = av.validate("session-B", make_click())
        assert ok, msg

    def test_clear_resets_history(self):
        av = ActionValidator()
        for _ in range(4):
            av.validate(SESSION, make_click())
        av.clear(SESSION)
        ok, msg = av.validate(SESSION, make_click())
        assert ok, msg

    def test_clear_resets_move_coords(self):
        av = ActionValidator()
        av.validate(SESSION, make_move(0.5, 0.5))
        av.validate(SESSION, make_click())
        av.clear(SESSION)
        # After clear, moving back to 0.5,0.5 should be allowed
        ok, msg = av.validate(SESSION, make_move(0.5, 0.5))
        assert ok, msg
