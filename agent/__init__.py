"""Cadence agent package.

ADK's `adk run` / `adk web` discover the agent via this package. Exposing
`root_agent` here (and importing the module) follows the ADK convention.
"""

from agent.agent import root_agent

__all__ = ["root_agent"]
