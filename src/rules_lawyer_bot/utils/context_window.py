"""Conversation-context trimming for the agent's model calls.

The OpenAI Agents ``Runner`` replays the full ``SQLiteSession`` history —
every prior user message, assistant message, tool call and *full tool
output* — on every model turn (and on each of the up-to-8 internal ReAct
turns within one run). Large ``read_full_document`` / search results
accumulate until the prompt exceeds the model's context window and the
provider rejects the request with HTTP 400.

This module provides a ``RunConfig.call_model_input_filter`` that bounds
every model call to a token budget. It trims oldest turns first and only
ever cuts at user-message boundaries, so a tool result is never separated
from the tool call it answers (which would itself trigger a 400).
"""

from __future__ import annotations

import json
from typing import Any

from src.rules_lawyer_bot.utils.logger import logger

# Conservative chars-per-token. The model is reached via OpenRouter, so the
# exact tokenizer is unknown; Russian/Cyrillic tokenizes far less efficiently
# than English. 3.0 deliberately over-counts to keep a safety margin below
# the hard provider limit.
_CHARS_PER_TOKEN = 3.0


def _item_chars(item: Any) -> int:
    """Serialized size of one transcript item, robust to non-dict items."""
    try:
        return len(json.dumps(item, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return len(str(item))


def estimate_tokens(items: list[Any]) -> int:
    """Estimate the token footprint of a list of transcript items.

    Conservative by design: a real tokenizer would usually report fewer
    tokens, so staying under this estimate stays under the real limit.
    """
    total_chars = sum(_item_chars(it) for it in items)
    return int(total_chars / _CHARS_PER_TOKEN) + len(items)


def _is_user_item(item: Any) -> bool:
    return isinstance(item, dict) and item.get("role") == "user"


def trim_model_input(model_data: Any, max_tokens: int) -> Any:
    """Return ``model_data`` trimmed so ``input`` fits within ``max_tokens``.

    ``instructions`` (the system prompt) are never trimmed. History is
    dropped oldest-first, always at user-message boundaries, so the kept
    suffix is a structurally valid transcript. The most recent user
    message is always retained even if it alone exceeds the budget (the
    ``read_full_document`` cap keeps a single turn small enough that this
    edge is not normally reached).
    """
    items: list[Any] = model_data.input

    if estimate_tokens(items) <= max_tokens:
        return model_data

    user_idxs = [i for i, it in enumerate(items) if _is_user_item(it)]

    if not user_idxs:
        # No user boundary to cut on (unusual). Best effort: drop oldest
        # items until under budget rather than send an oversized prompt.
        kept = list(items)
        while kept and estimate_tokens(kept) > max_tokens:
            kept.pop(0)
        model_data.input = kept
        logger.warning(
            "Context trimming: no user boundary; dropped %d/%d items",
            len(items) - len(kept),
            len(items),
        )
        return model_data

    # Keep the maximum amount of recent history: the earliest user-message
    # cut point whose suffix still fits the budget.
    chosen = user_idxs[-1]
    for cut in user_idxs:
        if estimate_tokens(items[cut:]) <= max_tokens:
            chosen = cut
            break

    trimmed = items[chosen:]
    if chosen > 0:
        logger.warning(
            "Context trimming: dropped %d oldest items (%d->%d est. tokens, "
            "budget %d)",
            chosen,
            estimate_tokens(items),
            estimate_tokens(trimmed),
            max_tokens,
        )
    model_data.input = trimmed
    return model_data


def build_context_trimming_filter(max_tokens: int):
    """Build a ``RunConfig.call_model_input_filter`` callable.

    The returned callable is invoked before every model call with a
    ``CallModelData``; it returns the (possibly trimmed) ``ModelInputData``.
    """

    def _filter(call_data: Any) -> Any:
        return trim_model_input(call_data.model_data, max_tokens=max_tokens)

    return _filter
