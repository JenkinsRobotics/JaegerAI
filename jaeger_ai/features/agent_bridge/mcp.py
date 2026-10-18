"""MCP adapter: token identity is relayed to the Gateway on every call."""

from urllib.parse import urlencode

from mcp.server.fastmcp import Context

from jaeger_ai.interfaces.mcp_server import _off_event_loop

from .service import enabled, key


def register(mcp, client_for_context):
    def call(ctx, method, path, body=None):
        enabled()
        return client_for_context(ctx)._call(method, path, body)

    @mcp.tool()
    @_off_event_loop
    def send_message(
        id: str,
        thread: str,
        to: str,
        kind: str,
        title: str,
        body: str,
        refs: list[str] | None = None,
        status_line: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Store untrusted message data; this never starts a goal or a tool."""
        return call(
            ctx,
            "POST",
            "/v1/agent-messages",
            {
                "id": id,
                "thread": thread,
                "to": to,
                "kind": kind,
                "title": title,
                "body": body,
                "refs": refs or [],
                "status_line": status_line,
            },
        )

    @mcp.tool()
    @_off_event_loop
    def list_messages(
        after: int = 0, limit: int = 50, ctx: Context | None = None
    ) -> dict:
        """Read only messages addressed to or sent by the authenticated caller."""
        return call(
            ctx,
            "GET",
            "/v1/agent-messages?" + urlencode({"after": after, "limit": limit}),
        )

    @mcp.tool()
    @_off_event_loop
    def get_thread(
        thread: str, after: int = 0, limit: int = 50, ctx: Context | None = None
    ) -> dict:
        """Read one participant-scoped thread with bounded cursor pagination."""
        return call(
            ctx,
            "GET",
            f"/v1/agent-threads/{key(thread)}?"
            + urlencode({"after": after, "limit": limit}),
        )

    @mcp.tool()
    @_off_event_loop
    def start_goal(
        goal: str,
        workspace_folder: str,
        thread: str,
        id: str,
        rea_tools: list[str] | None = None,
        ctx: Context | None = None,
    ) -> dict:
        """Request text-only analysis through Gateway admission; no tool execution.

        No tools are granted. REA pass-through is an incomplete acceptance
        item: unknown/mutating names are denied; known REA names fail closed
        until caller/thread/workspace handle confinement is implemented.
        """
        return call(
            ctx,
            "POST",
            "/v1/agent-goals",
            {
                "id": id,
                "thread": thread,
                "goal": goal,
                "workspace_folder": workspace_folder,
                "rea_tools": rea_tools or [],
            },
        )

    @mcp.tool()
    @_off_event_loop
    def goal_status(id: str, ctx: Context | None = None) -> dict:
        """Read text-only progress; this endpoint never reports verified tool execution."""
        return call(ctx, "GET", f"/v1/agent-goals/{key(id)}")

    @mcp.tool()
    @_off_event_loop
    def goal_result(id: str, ctx: Context | None = None) -> dict:
        """Retrieve text-only output; a model claim is not verified execution."""
        return call(ctx, "GET", f"/v1/agent-goals/{key(id)}")

    @mcp.tool()
    @_off_event_loop
    def cancel_goal(id: str, ctx: Context | None = None) -> dict:
        """Request cancellation through the existing Gateway cancellation owner."""
        return call(ctx, "POST", f"/v1/agent-goals/{key(id)}/cancel", {})
