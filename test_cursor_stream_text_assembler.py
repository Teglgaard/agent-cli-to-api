#!/usr/bin/env python3
"""
Cursor stream-json merge: live streaming without double-printing duplicate assistant bodies.

Legacy feed() vs feed_cursor() — see codex_gateway.stream_json_cli_stdin.TextAssembler.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

from codex_gateway.stream_json_cli_stdin import TextAssembler, extract_cursor_agent_delta


def _assistant_evt(content: str) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def test_prefix_extension_no_duplicate() -> None:
    a = TextAssembler()
    d1 = a.feed_cursor("Hello", dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    d2 = a.feed_cursor("Hello world", dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    assert d1 == "Hello"
    assert d2 == " world"
    assert a.text == "Hello world"


def test_identical_repeat_emits_no_second_delta() -> None:
    a = TextAssembler()
    a.feed_cursor("SAME", dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    d2 = a.feed_cursor("SAME", dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    assert d2 == ""
    assert a.text == "SAME"


def test_legacy_feed_non_monotonic_appends() -> None:
    """Plain feed() has no dedupe — two non-prefix bodies concatenate."""
    a = TextAssembler()
    first = "EXPLORING_LINE\nFULL_PLAN_V1_END"
    second = "LOCAL_SNAPSHOT_LINE\nFULL_PLAN_V2_SAME_SHAPE"
    assert a.feed(first) == first
    assert a.feed(second) == second
    assert a.text == first + second


def test_feed_cursor_suffix_overlap_emits_only_new_tail() -> None:
    a = TextAssembler()
    prefix = "START\n" + ("line\n" * 20)  # > 48 chars
    tail = ("SHARED_BRIDGE_CHUNK_" * 3) + "\n"  # > 48 chars overlap with previous stream
    a.feed_cursor(prefix + tail, dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    incoming = tail + "CONTINUATION_ONLY"
    d = a.feed_cursor(incoming, dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    assert d == "CONTINUATION_ONLY"
    assert a.text == prefix + tail + "CONTINUATION_ONLY"


def test_feed_cursor_suppresses_near_duplicate_long_resend() -> None:
    """Second assistant ~ identical to accumulated text → no extra delta."""
    base = "MIGRATION_PLAN_SECTION " * 25  # > 400 chars
    first = "INTRO\n" + base + "\nfooter_A\n"
    second = "INTRO\n" + base + "\nfooter_B\n"  # tiny tail change; ratio still very high
    a = TextAssembler()
    d1 = a.feed_cursor(first, dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    d2 = a.feed_cursor(second, dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    assert d1 == first
    assert d2 == ""
    assert a.text == first


def test_feed_cursor_short_non_monotonic_still_appends() -> None:
    """Below dedupe_min_chars, behave like append (avoid false suppression)."""
    a = TextAssembler()
    d1 = a.feed_cursor("EXPLORING\nSHORT", dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    d2 = a.feed_cursor("OTHER\nSHORT", dedupe_ratio=0.88, dedupe_min_chars=400, suffix_overlap_min=48)
    assert d1 == "EXPLORING\nSHORT"
    assert d2 == "OTHER\nSHORT"
    assert a.text == "EXPLORING\nSHORTOTHER\nSHORT"


def test_extract_cursor_agent_delta_uses_feed_cursor_under_settings() -> None:
    """Smoke: wiring through extract_cursor_agent_delta (imports settings)."""
    base = "BLOCK " * 80
    evt1 = _assistant_evt("A\n" + base)
    evt2 = _assistant_evt("B\n" + base)
    a = TextAssembler()
    d1 = extract_cursor_agent_delta(evt1, a)
    d2 = extract_cursor_agent_delta(evt2, a)
    assert d1.startswith("A\n")
    # Second body shares huge block; should suppress duplicate streaming if ratio high enough
    assert d2 == ""


def main() -> int:
    test_prefix_extension_no_duplicate()
    test_identical_repeat_emits_no_second_delta()
    test_legacy_feed_non_monotonic_appends()
    test_feed_cursor_suffix_overlap_emits_only_new_tail()
    test_feed_cursor_suppresses_near_duplicate_long_resend()
    test_feed_cursor_short_non_monotonic_still_appends()
    test_extract_cursor_agent_delta_uses_feed_cursor_under_settings()
    print("OK: cursor stream merge tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
