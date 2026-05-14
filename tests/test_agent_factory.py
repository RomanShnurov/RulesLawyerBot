"""Tests for the lazy agent factory."""
from unittest.mock import patch

import pytest


def test_get_rules_agent_returns_agent():
    """get_rules_agent() returns an Agent instance."""
    from src.rules_lawyer_bot.agent.definition import get_rules_agent

    agent = get_rules_agent()
    assert agent is not None
    assert hasattr(agent, "instructions")


def test_get_rules_agent_caches_instance():
    """Successive calls return the same cached instance."""
    from src.rules_lawyer_bot.agent.definition import (
        _reset_agent_cache_for_tests,
        get_rules_agent,
    )

    _reset_agent_cache_for_tests()

    a1 = get_rules_agent()
    a2 = get_rules_agent()
    assert a1 is a2


def test_reset_clears_cache():
    """_reset_agent_cache_for_tests forces a fresh build on next call."""
    from src.rules_lawyer_bot.agent.definition import (
        _reset_agent_cache_for_tests,
        get_rules_agent,
    )

    a1 = get_rules_agent()
    _reset_agent_cache_for_tests()
    a2 = get_rules_agent()

    assert a1 is not a2


def test_create_agent_not_called_at_import():
    """Importing agent.definition does NOT call create_agent at module load.

    This is the core invariant: the agent must be lazy.
    """
    import importlib

    import src.rules_lawyer_bot.agent.definition as defn

    with patch.object(defn, "create_agent") as mock_create:
        importlib.reload(defn)
        # Even after reload, create_agent should NOT have been called.
        mock_create.assert_not_called()
