"""jaeger-lsp — Fast post-edit diagnostics for Python, JSON, JS, and Swift."""

from .diagnostics import Diagnostic, DiagnosticReport, check_file_diagnostics

__all__ = ["Diagnostic", "DiagnosticReport", "check_file_diagnostics"]
