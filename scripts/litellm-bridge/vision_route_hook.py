"""
LiteLLM proxy: when the request includes image/vision content, rewrite the model to the
gateway deployment that uses Cursor `auto` instead of Composer 2 Fast.

`run_bridge.py` adds this directory to PYTHONPATH for the litellm child; we also insert
it here so imports work if LiteLLM loads the hook another way.

Environment:
  LITELLM_VISION_ROUTE          default "1"; set "0" to disable rewriting
  LITELLM_VISION_TARGET_MODEL   default "cursor-vision-auto" (must match model_list model_name)
  LITELLM_VISION_SOURCE_MODELS  optional comma-separated model names to rewrite (else built-in set)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_bridge_dir = Path(__file__).resolve().parent
if str(_bridge_dir) not in sys.path:
    sys.path.insert(0, str(_bridge_dir))

from litellm.integrations.custom_logger import CustomLogger

from vision_input_detect import messages_indicate_image_input

_DEFAULT_SOURCES = frozenset(
    {
        "cursor-composer-2-fast",
        "composer-2-fast",
        "claude-haiku-4-5-20251001",
    }
)


def _source_models() -> frozenset[str]:
    raw = (os.environ.get("LITELLM_VISION_SOURCE_MODELS") or "").strip()
    if not raw:
        return _DEFAULT_SOURCES
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return frozenset(parts) if parts else _DEFAULT_SOURCES


def _target_model() -> str:
    return (os.environ.get("LITELLM_VISION_TARGET_MODEL") or "cursor-vision-auto").strip() or "cursor-vision-auto"


def _hook_enabled() -> bool:
    return os.environ.get("LITELLM_VISION_ROUTE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class VisionRouteHook(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict: Any, cache: Any, data: dict, call_type: Any) -> Any:
        if not _hook_enabled():
            return data
        if not isinstance(data, dict):
            return data
        model = data.get("model")
        if not isinstance(model, str) or not model.strip():
            return data
        model = model.strip()
        if model not in _source_models():
            return data
        messages = data.get("messages")
        if not messages_indicate_image_input(messages):
            return data
        data = dict(data)
        data["model"] = _target_model()
        return data


vision_route_hook_instance = VisionRouteHook()
