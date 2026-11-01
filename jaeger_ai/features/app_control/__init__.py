"""AppControl: status, start/stop/restart, config and built-in invocation for Matthew's agent apps.

Every mutating action is a *proposal* that only Matthew can approve from the WebUI
(Machine tab). Nothing is ever applied automatically, never over MCP, never by a worker.
Design: ~/Documents/Jaeger-App-Control-Design-2026-10-31.md
"""
