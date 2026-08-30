"""
Core functionality needed for the bot to run.

This library exists to avoid circular imports and to clean up the mess that could be seen previously
in main.py. It's mostly used for type hints (especially Bot and Context).
"""
# ruff: noqa F403

from core.argument import *
from core.command import *
from core.slash_localization import *
from core.context import *
from core.bot import *
from core.hybrid import *
