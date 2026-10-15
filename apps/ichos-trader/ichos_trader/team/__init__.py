"""The bot team: scout (in the engine), strategist, advisor, traders, mild skeptic, manager, researcher.

See ``base.ROLES`` for one line on each, and docs/DESIGN.md for how one cycle passes through them.
"""

from .base import ROLES, Team

__all__ = ["ROLES", "Team"]
