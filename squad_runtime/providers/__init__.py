"""Provider subsystem for Squad Runtime.

Re-exports from the original providers module for backward compatibility.
"""

from __future__ import annotations

from .base import BaseProvider, ProviderHealth
from .impl import FakeCliProvider, LocalCliProvider, ProviderRegistry
from .process_runner import ProcessRunner
from .prompt_builder import PromptBuilder
from .rate_limiter import ProviderRateLimitConfig, ProviderRateLimiter, ProviderRateLimitSignal, ProviderRateLimitWait
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
    "ProviderRateLimitConfig",
    "ProviderRateLimiter",
    "ProviderRateLimitSignal",
    "ProviderRateLimitWait",
    "ResultParser",
    "Workspace",
]
