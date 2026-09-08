"""sapgui-mcp: cost-routed SAP automation over MCP.

Cheapest tier that can do the job, cheapest first:
  Tier 0 API (RFC/OData/sapcli) -> 1 recorded script -> 2 WebGUI -> 3 computer-use.
See docs/01-architecture.md.
"""

from .models import ErrorCode, ErrorInfo, Result, System, Task, Tier

__all__ = ["ErrorCode", "ErrorInfo", "Result", "System", "Task", "Tier"]
__version__ = "0.1.0"
