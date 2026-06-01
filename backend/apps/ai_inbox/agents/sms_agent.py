"""SMS agent entrypoint — thin wrapper over the channel-agnostic runner.

The agent loop moved to ``agents/runner.run_agent`` and is now driven
by a ``ChannelAdapter``. This module preserves the original
``run_agent(message=...)`` signature that ``services/dispatch.py``
calls, wiring up the SMS adapter. SMS behavior is unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.ai_inbox.agents.runner import run_agent as _run_agent
from apps.ai_inbox.channels.sms import SMSAdapter

if TYPE_CHECKING:
    from apps.messaging.models import Message


def run_agent(*, message: 'Message') -> None:
    """Run the SMS agent for one inbound Message. Never raises."""
    _run_agent(adapter=SMSAdapter(message))
