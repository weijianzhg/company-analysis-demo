"""Turn Strands tool lifecycle hooks into small, user-facing progress events."""

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider


class ToolProgress(HookProvider):
    def __init__(self, emit, servers):
        self.emit = emit
        self.servers = servers

    def register_hooks(self, registry, **kwargs):
        registry.add_callback(BeforeToolCallEvent, self.started)
        registry.add_callback(AfterToolCallEvent, self.finished)

    def send(self, tool_use, status):
        # Only emit metadata. Arguments, results and exception bodies stay private.
        self.emit({"type": "tool_call", "id": tool_use["toolUseId"],
                   "tool": tool_use["name"], "server": self.servers.get(tool_use["name"], "unknown"),
                   "status": status})

    def started(self, event):
        self.send(event.tool_use, "started")

    def finished(self, event):
        succeeded = event.exception is None and event.result.get("status") == "success"
        self.send(event.tool_use, "succeeded" if succeeded else "failed")
