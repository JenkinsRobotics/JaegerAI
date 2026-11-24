"""jaeger-tools: ToolRegistry, progressive discovery, swappable EditEngines, and RepoMap."""

from .diagnostics import Diagnostic, DiagnosticReport, diagnose_file
from .editors import ApplyPatchEditor, EditEngine, EditOutcome, SearchReplaceEditor
from .registry import ToolRegistry, ToolSpec
from .repomap import build_repo_map

__all__ = [
    "ApplyPatchEditor",
    "Diagnostic",
    "DiagnosticReport",
    "EditEngine",
    "EditOutcome",
    "SearchReplaceEditor",
    "ToolRegistry",
    "ToolSpec",
    "build_repo_map",
    "diagnose_file",
]
