"""Tool definitions and registry for the AI assistant."""

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ToolParam:
    """A parameter for a tool with type and description."""

    name: str
    param_type: str  # "string", "number", "boolean", "array", "object"
    description: str
    required: bool = True
    enum_values: Optional[List[str]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON schema."""
        schema = {
            "type": self.param_type,
            "description": self.description,
        }
        if self.enum_values:
            schema["enum"] = self.enum_values
        return schema


@dataclass
class ToolDefinition:
    """Complete definition of a tool for the model to discover."""

    name: str
    description: str
    parameters: List[ToolParam]
    handler: Callable[..., str]

    def to_schema(self) -> Dict[str, Any]:
        """Convert to JSON schema for LLM function calling."""
        properties = {}
        required = []
        for param in self.parameters:
            properties[param.name] = param.to_dict()
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class ToolRegistry:
    """Registry of available tools that the assistant can use."""

    def __init__(self):
        """Initialize the tool registry."""
        self.tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: List[ToolParam],
        handler: Callable[..., str],
    ) -> None:
        """Register a new tool."""
        self.tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
        )

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool by name."""
        return self.tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        """Return all registered tools."""
        return list(self.tools.values())

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas for LLM function calling."""
        return [tool.to_schema() for tool in self.list_tools()]

    def format_tools_for_prompt(self) -> str:
        """Format tools as text for inclusion in system prompt."""
        if not self.tools:
            return "No tools available."

        lines = ["Available tools:"]
        for tool in self.list_tools():
            lines.append(f"\n{tool.name}: {tool.description}")
            if tool.parameters:
                lines.append("  Parameters:")
                for param in tool.parameters:
                    req = "required" if param.required else "optional"
                    lines.append(f"    - {param.name} ({param.param_type}): {param.description} [{req}]")
        return "\n".join(lines)

    def call_tool(self, name: str, **kwargs) -> str:
        """Call a tool by name with the given arguments."""
        tool = self.get_tool(name)
        if not tool:
            return f"Error: Tool '{name}' not found."
        try:
            return tool.handler(**kwargs)
        except TypeError as e:
            return f"Error calling tool '{name}': Invalid arguments - {str(e)}"
        except Exception as e:
            return f"Error calling tool '{name}': {str(e)}"

    def parse_tool_calls(self, text: str) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Parse tool calls from model response text.

        Supports format:
        <tool_call>
        name: tool_name
        arguments: {"param1": "value1", "param2": "value2"}
        </tool_call>

        Returns:
            List of (tool_name, arguments_dict) tuples
        """
        tool_calls = []
        pattern = r"<tool_call>\s*name:\s*(\w+)\s*arguments:\s*({.*?})\s*</tool_call>"

        for match in re.finditer(pattern, text, re.DOTALL):
            tool_name = match.group(1)
            args_str = match.group(2)
            try:
                arguments = json.loads(args_str)
                tool_calls.append((tool_name, arguments))
            except json.JSONDecodeError:
                pass

        return tool_calls


# Global registry
TOOL_REGISTRY = ToolRegistry()


# ============================================================================
# Built-in Tools
# ============================================================================


def builtin_get_time() -> str:
    """Get the current date and time in ISO format."""
    from datetime import datetime

    return datetime.now().isoformat()


def builtin_add_numbers(a: float, b: float) -> str:
    """Add two numbers together."""
    result = a + b
    return f"{a} + {b} = {result}"


def builtin_multiply_numbers(a: float, b: float) -> str:
    """Multiply two numbers together."""
    result = a * b
    return f"{a} * {b} = {result}"


def builtin_search_web(query: str, engine: str = "all", freshness: str = "month") -> str:
    '''Search current web sources and label source age for answer synthesis.'''
    from web_access import answer
    return answer(query, engine=engine, freshness=freshness)


def builtin_fetch_webpage(url: str) -> str:
    '''Open a discovered public link and return readable text.'''
    from web_access import open_link
    return open_link(url)


def builtin_get_weather(location: str) -> str:
    """
    Get weather information for a location.

    Note: This is a placeholder. In a real implementation,
    this would call a weather API.
    """
    return f"[Weather placeholder] Would fetch weather for: {location}"


def builtin_list_tools() -> str:
    """List all available tools."""
    tools = TOOL_REGISTRY.list_tools()
    if not tools:
        return "No tools available."
    return "Available tools:\n" + "\n".join(
        f"  - {tool.name}: {tool.description}" for tool in tools
    )


# ============================================================================
# Register Built-in Tools
# ============================================================================

TOOL_REGISTRY.register(
    name="get_time",
    description="Get the current date and time in ISO format.",
    parameters=[],
    handler=builtin_get_time,
)

TOOL_REGISTRY.register(
    name="add_numbers",
    description="Add two numbers together.",
    parameters=[
        ToolParam(
            name="a",
            param_type="number",
            description="The first number",
            required=True,
        ),
        ToolParam(
            name="b",
            param_type="number",
            description="The second number",
            required=True,
        ),
    ],
    handler=builtin_add_numbers,
)

TOOL_REGISTRY.register(
    name="multiply_numbers",
    description="Multiply two numbers together.",
    parameters=[
        ToolParam(
            name="a",
            param_type="number",
            description="The first number",
            required=True,
        ),
        ToolParam(
            name="b",
            param_type="number",
            description="The second number",
            required=True,
        ),
    ],
    handler=builtin_multiply_numbers,
)

TOOL_REGISTRY.register(
    name="search_web",
    description="Research a question using web sources and return source text for an answer. Use engine='all' for most thorough results.",
    parameters=[
            ToolParam(
            name="query",
            param_type="string",
            description="The current question to research",
            required=True,
        ),
        ToolParam(
            name="engine",
            param_type="string",
            description="Search engine: all, duckgo, google, or bing",
            required=False,
            enum_values=["all", "duckgo", "google", "bing"],
        ),
        ToolParam(
            name="freshness",
            param_type="string",
            description="Preferred source age: day, week, month, or any",
            required=False,
            enum_values=["day", "week", "month", "any"],
        ),
    ],
    handler=builtin_search_web,
)


TOOL_REGISTRY.register(
    name="open_link",
    description="Open a discovered public HTTP or HTTPS link and inspect its readable content.",
    parameters=[ToolParam(name="url", param_type="string", description="The discovered public page URL", required=True)],
    handler=builtin_fetch_webpage,
)

TOOL_REGISTRY.register(
    name="fetch_webpage",
    description="Fetch readable text from a public HTTP or HTTPS web page.",
    parameters=[
        ToolParam(name="url", param_type="string", description="The public page URL", required=True),
    ],
    handler=builtin_fetch_webpage,
)

TOOL_REGISTRY.register(
    name="get_weather",
    description="Get current weather information for a location. (Placeholder for now.)",
    parameters=[
        ToolParam(
            name="location",
            param_type="string",
            description="The city or location name",
            required=True,
        ),
    ],
    handler=builtin_get_weather,
)

TOOL_REGISTRY.register(
    name="list_tools",
    description="List all available tools the assistant can use.",
    parameters=[],
    handler=builtin_list_tools,
)


# ============================================================================
# Computer Controls, Google & YouTube Tools
# ============================================================================


def builtin_system_clipboard(action: str = "get", text: str = "") -> str:
    """Read or write text to/from OS clipboard."""
    from connectors import CONNECTOR_REGISTRY

    if action.lower() == "set":
        res = CONNECTOR_REGISTRY.execute("system_control", "set_clipboard", text=text)
        return f"Copied {len(text)} chars to clipboard." if res.get("success") else f"Error: {res.get('error')}"
    else:
        res = CONNECTOR_REGISTRY.execute("system_control", "get_clipboard")
        return f"Clipboard: {res.get('clipboard', '')}" if res.get("success") else f"Error: {res.get('error')}"


def builtin_system_screenshot(output_path: str = "screenshot.png") -> str:
    """Capture a screen snapshot to file."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("system_control", "take_screenshot", output_path=output_path)
    return f"Screenshot saved to {res.get('path')}" if res.get("success") else f"Error: {res.get('error')}"


def builtin_google_search(query: str, open_browser: bool = False) -> str:
    """Perform Google search and optionally open in browser."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("google_services", "search", query=query, open_browser=open_browser)
    return f"Google Search ({res.get('url')}):\n{res.get('summary', '')}" if res.get("success") else f"Error: {res.get('error')}"


def builtin_youtube_search(query: str, open_browser: bool = False) -> str:
    """Search videos on YouTube."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("youtube", "search", query=query, open_browser=open_browser)
    return f"YouTube Results ({res.get('search_url')}):\n{res.get('summary', '')}" if res.get("success") else f"Error: {res.get('error')}"


def builtin_youtube_play(query_or_url: str, music: bool = False) -> str:
    """Play a YouTube video or song."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("youtube", "play", query_or_url=query_or_url, music=music)
    return f"Opening YouTube: {res.get('url')}" if res.get("success") else f"Error: {res.get('error')}"


TOOL_REGISTRY.register(
    name="system_clipboard",
    description="Read or set the system clipboard text.",
    parameters=[
        ToolParam(name="action", param_type="string", description="'get' to read or 'set' to copy", required=True, enum_values=["get", "set"]),
        ToolParam(name="text", param_type="string", description="Text to copy when action is 'set'", required=False),
    ],
    handler=builtin_system_clipboard,
)

TOOL_REGISTRY.register(
    name="system_screenshot",
    description="Capture a desktop screenshot and save to a local PNG file.",
    parameters=[
        ToolParam(name="output_path", param_type="string", description="File destination path", required=False),
    ],
    handler=builtin_system_screenshot,
)

TOOL_REGISTRY.register(
    name="google_search",
    description="Search Google for information, current queries, or open in browser.",
    parameters=[
        ToolParam(name="query", param_type="string", description="Search query string", required=True),
        ToolParam(name="open_browser", param_type="boolean", description="Whether to open the search page in browser", required=False),
    ],
    handler=builtin_google_search,
)

TOOL_REGISTRY.register(
    name="youtube_search",
    description="Search YouTube for videos, tutorials, or music.",
    parameters=[
        ToolParam(name="query", param_type="string", description="Search query string", required=True),
        ToolParam(name="open_browser", param_type="boolean", description="Whether to open results in browser", required=False),
    ],
    handler=builtin_youtube_search,
)

TOOL_REGISTRY.register(
    name="youtube_play",
    description="Play a video or song on YouTube / YouTube Music.",
    parameters=[
        ToolParam(name="query_or_url", param_type="string", description="Video title, artist, or YouTube URL", required=True),
        ToolParam(name="music", param_type="boolean", description="Open on YouTube Music instead of regular YouTube", required=False),
    ],
    handler=builtin_youtube_play,
)

# ============================================================================
# File, Folder, Graph, Media & Prompt-Compression Tools
# ============================================================================


def builtin_read_file(path: str, max_chars: int = 20000) -> str:
    '''Read a local text file (or report media/binary metadata) safely.'''
    from folder_reader import FolderReader, FolderReaderError
    try:
        result = FolderReader().read_file("__direct__", path, max_chars=max_chars)
    except FolderReaderError:
        # Fall back to a direct, sandboxed read of an absolute path.
        from pathlib import Path
        target = Path(path).expanduser().resolve()
        if not target.exists() or not target.is_file():
            return f"Error: file not found: {path}"
        suffix = target.suffix.lower()
        size = target.stat().st_size
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip", ".tar", ".gz", ".7z", ".rar"}:
            return f"[{suffix.upper()} media/binary file — {size} bytes. Use analyze_media for details.]"
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            return f"Error reading file: {error}"
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated: showing first {max_chars} of {len(text)} chars]"
        return text
    return result.get("content", "")


def builtin_list_folder(path: str, limit: int = 100) -> str:
    '''List files inside a local folder (any format).'''
    from pathlib import Path
    folder = Path(path).expanduser().resolve()
    if not folder.exists() or not folder.is_dir():
        return f"Error: folder not found: {path}"
    lines = []
    for f in sorted(folder.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(folder).as_posix()
        lines.append(f"{rel} ({f.stat().st_size} bytes)")
        if len(lines) >= limit:
            lines.append(f"... and more ({limit}+ files)")
            break
    return "\n".join(lines) if lines else "(empty folder)"


def builtin_read_graph(text: str) -> str:
    '''Parse entities and relationships from text or a diagram.'''
    from graph_engine import GraphEngine
    result = GraphEngine.read_graph(text)
    lines = [f"Parsed {result['node_count']} nodes, {result['edge_count']} edges:"]
    for edge in result.get("edges", []):
        label = f" ({edge.get('label')})" if edge.get("label") else ""
        lines.append(f"  {edge['from']} --> {edge['to']}{label}")
    return "\n".join(lines)


def builtin_analyze_media(path: str) -> str:
    '''Analyze an image or video file: format, dimensions, and strategy.'''
    from media_analyzer import MediaAnalyzer
    result = MediaAnalyzer.analyze_picture(path)
    if result.get("success"):
        return (
            f"Image: {result['filename']} ({result['format']}, {result['size_bytes']} bytes, "
            f"{result.get('width')}x{result.get('height')})"
        )
    video = MediaAnalyzer.analyze_video(path)
    if video.get("success"):
        strategy = video.get("analysis_strategy", {})
        return (
            f"Video: {video['filename']} ({video['format']}, {video['size_mb']} MB). "
            f"Sampling: {strategy.get('sampling_rate_fps')} fps, "
            f"keyframes: {strategy.get('keyframes_recommended')}"
        )
    return f"Error: {result.get('error') or video.get('error') or 'unsupported media'}"


def builtin_compress_prompt(text: str, path: str = "compressed_prompt.txt") -> str:
    '''Compress a large prompt into a single local file the assistant can read.'''
    from pathlib import Path
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return f"Prompt saved to {target} ({len(text)} chars). Read it with read_file."

TOOL_REGISTRY.register(
    name="read_file",
    description="Read a local text file (code, docs, config) or report media/binary metadata. Use for files the user attached or referenced.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Absolute or relative path to the file", required=True),
        ToolParam(name="max_chars", param_type="number", description="Maximum characters to read (default 20000)", required=False),
    ],
    handler=builtin_read_file,
)

TOOL_REGISTRY.register(
    name="list_folder",
    description="List files inside a local folder, any format, with sizes.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Path to the folder", required=True),
        ToolParam(name="limit", param_type="number", description="Maximum entries (default 100)", required=False),
    ],
    handler=builtin_list_folder,
)

TOOL_REGISTRY.register(
    name="read_graph",
    description="Parse entities and relationships from text or a diagram into a structured graph.",
    parameters=[
        ToolParam(name="text", param_type="string", description="Text or diagram to parse", required=True),
    ],
    handler=builtin_read_graph,
)

TOOL_REGISTRY.register(
    name="analyze_media",
    description="Analyze an image or video file: format, dimensions, size, and a frame-sampling strategy.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Path to the image or video file", required=True),
    ],
    handler=builtin_analyze_media,
)

TOOL_REGISTRY.register(
    name="compress_prompt",
    description="Save a large prompt or context into a single local file that can be read back later.",
    parameters=[
        ToolParam(name="text", param_type="string", description="The large prompt/context text", required=True),
        ToolParam(name="path", param_type="string", description="Destination file path (default compressed_prompt.txt)", required=False),
    ],
    handler=builtin_compress_prompt,
)


# ============================================================================
# Math, Knowledge, Graph Creation & Data Understanding Tools
# ============================================================================


def builtin_solve_math(expression: str) -> str:
    """Evaluate a math expression or solve an equation in x."""
    from math_engine import solve_math
    return solve_math(expression)


def builtin_search_knowledge(query: str) -> str:
    """Search the permanent general knowledge base (history, math, science, units)."""
    from knowledge import get_knowledge
    return get_knowledge().search_text(query)


def builtin_create_graph(nodes_json: str, edges_json: str, graph_type: str = "flowchart", direction: str = "TD") -> str:
    """Create a Mermaid/ASCII graph from JSON node and edge definitions."""
    import json
    from graph_engine import GraphEngine
    try:
        nodes = json.loads(nodes_json) if isinstance(nodes_json, str) else nodes_json
        edges = json.loads(edges_json) if isinstance(edges_json, str) else edges_json
    except json.JSONDecodeError as error:
        return f"Error: invalid JSON — {error}"
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return "Error: nodes and edges must be JSON arrays."
    result = GraphEngine.create_graph(nodes, edges, graph_type=graph_type, direction=direction)
    return f"{result['ascii']}\n\nMermaid:\n```mermaid\n{result['mermaid']}\n```"


def builtin_summarize_data(path: str, max_rows: int = 1000) -> str:
    """Understand a CSV/JSON data file: structure, columns, and basic statistics."""
    import csv
    import json as jsonlib
    from pathlib import Path
    from statistics import mean, median

    target = Path(path).expanduser().resolve()
    if not target.exists() or not target.is_file():
        return f"Error: file not found: {path}"

    suffix = target.suffix.lower()
    rows: list = []
    try:
        if suffix == ".json":
            data = jsonlib.loads(target.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows = list(data.values())
            elif isinstance(data, list):
                rows = data
            else:
                return f"Error: unsupported JSON structure ({type(data).__name__})"
        elif suffix in {".csv", ".tsv", ".txt"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            with target.open("r", encoding="utf-8", errors="replace") as handle:
                reader = csv.reader(handle, delimiter=delimiter)
                header = next(reader, None)
                rows = [dict(zip(header, row)) for row in reader if header]
        else:
            return f"Error: unsupported data format ({suffix}). Use .csv, .tsv, or .json."
    except (OSError, jsonlib.JSONDecodeError, csv.Error) as error:
        return f"Error reading data file: {error}"

    if not rows:
        return f"File {target.name} contains no data rows."
    rows = rows[:max_rows]

    if isinstance(rows[0], dict):
        columns = list(rows[0].keys())
        lines = [
            f"Data file: {target.name} ({len(rows)} rows, {len(columns)} columns)",
            f"Columns: {', '.join(columns)}",
        ]
        for col in columns:
            numeric = []
            for row in rows:
                value = row.get(col)
                if isinstance(value, (int, float)):
                    numeric.append(float(value))
                else:
                    try:
                        numeric.append(float(value))
                    except (TypeError, ValueError):
                        continue
            if numeric:
                values = sorted(numeric)
                lines.append(
                    f"  {col}: min={values[0]:g}, max={values[-1]:g}, "
                    f"mean={mean(numeric):.2f}, median={median(numeric):.2f}"
                )
            else:
                unique = len({str(row.get(col)) for row in rows})
                lines.append(f"  {col}: non-numeric, {unique} unique values")
        return "\n".join(lines)

    return f"Data file: {target.name} ({len(rows)} rows)\nFirst row: {rows[0]}"


TOOL_REGISTRY.register(
    name="solve_math",
    description="Evaluate a math expression or solve an equation in x. Handles sqrt, powers, trig, logs, constants (pi, e), unicode symbols (√, ×, ÷, ²), and implicit multiplication (2x, 3(4+5)).",
    parameters=[
        ToolParam(name="expression", param_type="string", description="Math expression (e.g. 'sqrt(144) + 2^5') or equation (e.g. '2x + 3 = 11')", required=True),
    ],
    handler=builtin_solve_math,
)

TOOL_REGISTRY.register(
    name="search_knowledge",
    description="Search the permanent general knowledge base: history, math formulas, science, geography, technology, units and conversions, common facts.",
    parameters=[
        ToolParam(name="query", param_type="string", description="What to look up (e.g. 'quadratic formula', 'WW2 dates', 'km to miles')", required=True),
    ],
    handler=builtin_search_knowledge,
)

TOOL_REGISTRY.register(
    name="create_graph",
    description="Create a Mermaid and ASCII graph (flowchart, sequence, state diagram) from JSON node and edge definitions.",
    parameters=[
        ToolParam(name="nodes_json", param_type="string", description="JSON array of nodes: [{\"id\": \"A\", \"label\": \"Node\"}]", required=True),
        ToolParam(name="edges_json", param_type="string", description="JSON array of edges: [{\"from\": \"A\", \"to\": \"B\", \"label\": \"rel\"}]", required=True),
        ToolParam(name="graph_type", param_type="string", description="flowchart, sequencediagram, or stateDiagram", required=False, enum_values=["flowchart", "sequencediagram", "stateDiagram"]),
        ToolParam(name="direction", param_type="string", description="TD (top-down) or LR (left-right)", required=False, enum_values=["TD", "LR"]),
    ],
    handler=builtin_create_graph,
)

TOOL_REGISTRY.register(
    name="summarize_data",
    description="Understand a CSV, TSV, or JSON data file: structure, columns, numeric ranges, means, medians, and unique values.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Path to the data file", required=True),
        ToolParam(name="max_rows", param_type="number", description="Maximum rows to analyze (default 1000)", required=False),
    ],
    handler=builtin_summarize_data,
)


# ============================================================================
# Finance Tools (live market data + permanent financial knowledge)
# ============================================================================


def builtin_stock_quote(symbols: str) -> str:
    """Fetch live quotes for one or more stock symbols."""
    from finance import quote_text
    return quote_text(symbols)


def builtin_stock_history(symbol: str, range: str = "3mo") -> str:
    """Fetch daily price history for a symbol."""
    from finance import history_text
    return history_text(symbol, range=range)


def builtin_market_status() -> str:
    """Report whether US stock markets are currently open."""
    from connectors import CONNECTOR_REGISTRY

    result = CONNECTOR_REGISTRY.execute("finance", "market_status")
    if not result.get("success"):
        return f"Error: {result.get('error', 'unknown')}"
    state = "OPEN" if result.get("open") else "CLOSED"
    return f"US stock markets are currently {state} (Eastern Time)."


def builtin_search_finance_knowledge(query: str) -> str:
    """Search the permanent financial literacy knowledge base."""
    from finance import get_finance_knowledge
    return get_finance_knowledge().search_text(query)


TOOL_REGISTRY.register(
    name="stock_quote",
    description="Fetch live stock quotes for one or more symbols (e.g. 'AAPL, MSFT'). Requires web access.",
    parameters=[
        ToolParam(name="symbols", param_type="string", description="Comma-separated ticker symbols", required=True),
    ],
    handler=builtin_stock_quote,
)

TOOL_REGISTRY.register(
    name="stock_history",
    description="Fetch daily price history for a symbol over a range (1mo, 3mo, 6mo, 1y, 2y, 5y). Requires web access.",
    parameters=[
        ToolParam(name="symbol", param_type="string", description="Ticker symbol (e.g. AAPL)", required=True),
        ToolParam(name="range", param_type="string", description="History range", required=False, enum_values=["1mo", "3mo", "6mo", "1y", "2y", "5y"]),
    ],
    handler=builtin_stock_history,
)

TOOL_REGISTRY.register(
    name="market_status",
    description="Report whether US stock markets are currently open or closed.",
    parameters=[],
    handler=builtin_market_status,
)

TOOL_REGISTRY.register(
    name="search_finance_knowledge",
    description="Search the permanent financial literacy knowledge base: valuation ratios, indicators, when to invest or sell, risk management, strategies.",
    parameters=[
        ToolParam(name="query", param_type="string", description="What to look up (e.g. 'P/E ratio', 'when to sell', 'dollar cost averaging')", required=True),
    ],
    handler=builtin_search_finance_knowledge,
)


# ============================================================================
# Voice Tools (talk back, listen, voices, voice ID)
# ============================================================================


def builtin_speak(text: str, voice: str = "") -> str:
    """Speak text aloud through the selected voice (TTS)."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("voice", "speak", text=text, voice=voice or None)
    return res.get("message", "ok") if res.get("success") else f"Error: {res.get('error')}"


def builtin_listen(timeout: int = 10) -> str:
    """Listen to the microphone and return recognized speech (STT)."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("voice", "listen", timeout=timeout)
    return res.get("text", "[no speech]") if res.get("success") else f"Error: {res.get('error')}"


def builtin_list_voices() -> str:
    """List installed voices."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("voice", "list_voices")
    if not res.get("success"):
        return f"Error: {res.get('error')}"
    voices = res.get("voices", [])
    if not voices:
        return "No voices installed."
    return "Installed voices:\n" + "\n".join(
        f"  - {v['name']} ({v['gender']}, {v['culture']})" for v in voices
    )


def builtin_set_voice(name: str) -> str:
    """Select which installed voice speaks."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("voice", "set_voice", name=name)
    return res.get("message", "ok") if res.get("success") else f"Error: {res.get('error')}"


def builtin_voice_scan(mode: str = "status", label: str = "user") -> str:
    """Enroll, verify, or check the status of the user's voice ID."""
    from connectors import CONNECTOR_REGISTRY

    res = CONNECTOR_REGISTRY.execute("voice", "voice_scan", mode=mode, label=label)
    if not res.get("success"):
        return f"Error: {res.get('error')}"
    if mode == "status":
        state = "enrolled" if res.get("enrolled") else "not enrolled"
        return (
            f"Voice ID: {state}. Voiceprint(s): {', '.join(res.get('voiceprints', [])) or 'none'}. "
            f"Active voice: {res.get('voice') or 'none'}. Mic: {res.get('mic') or 'not found'}."
        )
    return res.get("message", "ok")


TOOL_REGISTRY.register(
    name="speak",
    description="Speak text aloud through the selected voice (text-to-speech).",
    parameters=[
        ToolParam(name="text", param_type="string", description="Text to speak aloud", required=True),
        ToolParam(name="voice", param_type="string", description="Optional voice name (e.g. 'Microsoft Zira Desktop')", required=False),
    ],
    handler=builtin_speak,
)

TOOL_REGISTRY.register(
    name="listen",
    description="Listen to the microphone and return the recognized speech (speech-to-text).",
    parameters=[
        ToolParam(name="timeout", param_type="number", description="Seconds to listen (default 10)", required=False),
    ],
    handler=builtin_listen,
)

TOOL_REGISTRY.register(
    name="list_voices",
    description="List the installed text-to-speech voices.",
    parameters=[],
    handler=builtin_list_voices,
)

TOOL_REGISTRY.register(
    name="set_voice",
    description="Select which installed voice speaks (e.g. 'Microsoft Zira Desktop').",
    parameters=[
        ToolParam(name="name", param_type="string", description="Voice name or partial match", required=True),
    ],
    handler=builtin_set_voice,
)

TOOL_REGISTRY.register(
    name="voice_scan",
    description="Voice ID: enroll (mode='enroll'), verify (mode='verify'), or check status (mode='status').",
    parameters=[
        ToolParam(name="mode", param_type="string", description="enroll, verify, or status", required=False, enum_values=["enroll", "verify", "status"]),
        ToolParam(name="label", param_type="string", description="Label for the voiceprint when enrolling (default 'user')", required=False),
    ],
    handler=builtin_voice_scan,
)


# ---------------------------------------------------------------------------
# Obsidian Vault Tools
# ---------------------------------------------------------------------------

def builtin_obsidian_search(query: str) -> str:
    """Search notes in the Obsidian vault."""
    from connectors import CONNECTOR_REGISTRY
    result = CONNECTOR_REGISTRY.execute("obsidian", "search", query=query)
    if not result.get("success"):
        return f"Obsidian search failed: {result.get('error')}"
    matches = result.get("matches", [])
    if not matches:
        return f"No notes matching '{query}' found in Obsidian."
    lines = [f"Found {len(matches)} matching note(s) for '{query}':"]
    for m in matches[:10]:
        fn = m.get("filename", str(m))
        lines.append(f"- {fn}")
    return "\n".join(lines)


def builtin_obsidian_read_note(path: str) -> str:
    """Read content of a note from Obsidian vault."""
    from connectors import CONNECTOR_REGISTRY
    result = CONNECTOR_REGISTRY.execute("obsidian", "read", path=path)
    if not result.get("success"):
        return f"Obsidian read failed: {result.get('error')}"
    return f"Content of '{result.get('path')}':\n\n{result.get('content')}"


def builtin_obsidian_write_note(path: str, content: str) -> str:
    """Create or update a note in the Obsidian vault."""
    from connectors import CONNECTOR_REGISTRY
    result = CONNECTOR_REGISTRY.execute("obsidian", "write", path=path, content=content)
    if not result.get("success"):
        return f"Obsidian write failed: {result.get('error')}"
    return f"Successfully saved note '{result.get('path')}' ({result.get('bytes_written')} bytes) in Obsidian."


def builtin_obsidian_append_note(path: str, content: str) -> str:
    """Append content to an existing note in the Obsidian vault."""
    from connectors import CONNECTOR_REGISTRY
    result = CONNECTOR_REGISTRY.execute("obsidian", "append", path=path, content=content)
    if not result.get("success"):
        return f"Obsidian append failed: {result.get('error')}"
    return f"Successfully appended content to note '{result.get('path')}' in Obsidian."


def builtin_obsidian_list_notes(directory: str = "") -> str:
    """List notes in the Obsidian vault."""
    from connectors import CONNECTOR_REGISTRY
    result = CONNECTOR_REGISTRY.execute("obsidian", "list", directory=directory)
    if not result.get("success"):
        return f"Obsidian list failed: {result.get('error')}"
    files = result.get("files", [])
    if not files:
        return "No notes found in vault directory."
    return f"Obsidian vault notes ({len(files)} total):\n" + "\n".join(f"- {f}" for f in files[:25])


TOOL_REGISTRY.register(
    name="obsidian_search",
    description="Search for notes and resources in your Obsidian vault.",
    parameters=[
        ToolParam(name="query", param_type="string", description="Keyword or topic to search for in Obsidian notes", required=True),
    ],
    handler=builtin_obsidian_search,
)

TOOL_REGISTRY.register(
    name="obsidian_read_note",
    description="Read the markdown content of a note from your Obsidian vault.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Relative path or name of the note (e.g. 'Projects/Agent.md')", required=True),
    ],
    handler=builtin_obsidian_read_note,
)

TOOL_REGISTRY.register(
    name="obsidian_write_note",
    description="Create or overwrite a markdown note in your Obsidian vault.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Relative path or name of the note in the vault", required=True),
        ToolParam(name="content", param_type="string", description="Markdown text content to write", required=True),
    ],
    handler=builtin_obsidian_write_note,
)

TOOL_REGISTRY.register(
    name="obsidian_append_note",
    description="Append content to an existing note in your Obsidian vault.",
    parameters=[
        ToolParam(name="path", param_type="string", description="Relative path or name of the note in the vault", required=True),
        ToolParam(name="content", param_type="string", description="Markdown text content to append", required=True),
    ],
    handler=builtin_obsidian_append_note,
)

TOOL_REGISTRY.register(
    name="obsidian_list_notes",
    description="List all notes or folder contents in your Obsidian vault.",
    parameters=[
        ToolParam(name="directory", param_type="string", description="Optional subfolder inside the vault to list", required=False),
    ],
    handler=builtin_obsidian_list_notes,
)

