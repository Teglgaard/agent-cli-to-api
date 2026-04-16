"""
Detect image / vision payloads in chat-style message lists.

Used by the LiteLLM proxy hook and unit tests (no litellm dependency).
"""

from __future__ import annotations

from typing import Any

# OpenAI-style (image_url), Anthropic-style (image), and newer multimodal aliases.
_IMAGE_BLOCK_TYPES = frozenset(
    {
        "image",
        "image_url",
        "input_image",
    }
)


def _tree_has_image(node: Any, depth: int = 0) -> bool:
    if depth > 32:
        return False
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t in _IMAGE_BLOCK_TYPES:
            return True
        for v in node.values():
            if _tree_has_image(v, depth + 1):
                return True
    elif isinstance(node, list):
        for x in node:
            if _tree_has_image(x, depth + 1):
                return True
    return False


def messages_indicate_image_input(messages: Any) -> bool:
    """True if any message content includes an image / vision block."""
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            continue
        if _tree_has_image(content):
            return True
    return False


def last_user_message_has_image(messages: Any) -> bool:
    """
    True only if the *latest* user turn contains image / vision blocks.

    Older messages may still carry images from prior turns; ignoring those avoids
    routing every follow-up request (text-only) to a vision-capable model after
    the first image was sent.
    """
    if not isinstance(messages, list):
        return False
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = (msg.get("role") or "").strip().lower()
        if role not in ("user", "human"):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return False
        return _tree_has_image(content)
    return False
