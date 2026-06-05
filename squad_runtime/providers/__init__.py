"""Provider subsystem for Squad Runtime.

Re-exports from the original providers module for backward compatibility.
"""

from __future__ import annotations

from .base import BaseProvider, ProviderHealth
from .impl import FakeCliProvider, LocalCliProvider, ProviderRegistry
from .process_runner import ProcessRunner
from .prompt_builder import PromptBuilder
from .result_parser import ResultParser
from .workspace import Workspace

__all__ = [
    "BaseProvider",
    "FakeCliProvider",
    "LocalCliProvider",
    "ProcessRunner",
    "PromptBuilder",
    "ProviderHealth",
    "ProviderRegistry",
    "ResultParser",
    "Workspace",
]
