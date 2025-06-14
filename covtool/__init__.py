"""covtool - manipulate coverage traces for dynamic analysis"""

from .drcov import (
    read,
    write,
    builder,
    CoverageData,
    BasicBlock,
    ModuleEntry,
    FileHeader,
    ModuleTableVersion,
    DrCovError,
    CoverageBuilder,
)
from .core import CoverageSet

__all__ = [
    "read",
    "write",
    "builder",
    "CoverageData",
    "BasicBlock",
    "ModuleEntry",
    "FileHeader",
    "ModuleTableVersion",
    "DrCovError",
    "CoverageBuilder",
    "CoverageSet",
]
