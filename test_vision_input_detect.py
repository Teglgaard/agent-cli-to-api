"""Unit tests for scripts/litellm-bridge/vision_input_detect.py (no LiteLLM import)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts" / "litellm-bridge"))

from vision_input_detect import messages_indicate_image_input  # noqa: E402


def test_text_only_messages_false() -> None:
    assert not messages_indicate_image_input(
        [{"role": "user", "content": "hello"}]
    )


def test_openai_image_url_true() -> None:
    assert messages_indicate_image_input(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            }
        ]
    )


def test_anthropic_image_block_true() -> None:
    assert messages_indicate_image_input(
        [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": "/9j/4AAQ",
                        },
                    },
                    {"type": "text", "text": "tap the button"},
                ],
            }
        ]
    )


def test_nested_content_true() -> None:
    assert messages_indicate_image_input(
        [
            {
                "role": "user",
                "content": [{"type": "message", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}],
            }
        ]
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
