"""The nine function tools exposed to OpenAI Realtime."""


def function_tool(name: str, description: str, properties: dict | None = None) -> dict:
    properties = properties or {}
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS = [
    function_tool(
        "start_screenshare",
        "Show a requested public HTTPS webpage. Does not read it or post its link.",
        {"url": {"type": "string", "description": "The public HTTPS URL to display."}},
    ),
    function_tool(
        "send_chat_message",
        "Post requested text to everyone. Use send_current_page_link for the selected page.",
        {"message": {"type": "string", "minLength": 1, "maxLength": 500}},
    ),
    function_tool(
        "send_current_page_link",
        "Post the exact last successfully selected webpage URL, even after sharing stops.",
    ),
    function_tool(
        "stop_screenshare",
        "Stop sharing the page. Keep the voice conversation and last page URL.",
    ),
    function_tool("leave_call", "Leave this meeting when explicitly asked to leave."),
    function_tool("mute_agent", "Mute speech immediately. Continue accepting requested tools."),
    function_tool("unmute_agent", "Enable new speech; never replay unheard responses."),
    function_tool(
        "stop_listening",
        "Pause answers and actions until a separate addressed start-listening request. Preserve mute.",
    ),
    function_tool(
        "start_listening",
        "Resume requests, preserving mute and discarding skipped requests.",
    ),
]

CONTROL_TOOLS = {"mute_agent", "unmute_agent", "stop_listening", "start_listening", "leave_call"}
