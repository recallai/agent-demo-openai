"""Validate and execute model-requested actions once per participant request."""

import json

from app.meeting_tools import MeetingTools, ToolError
from app.tool_schema import TOOL_SCHEMAS


class ToolExecutor:
    def __init__(self, tools: MeetingTools):
        self.tools = tools
        self._schemas = {schema["name"]: schema for schema in TOOL_SCHEMAS}
        self._attempts: dict[tuple, dict] = {}

    async def execute(self, call: dict, turn: int) -> dict:
        name = call.get("name")
        try:
            arguments = json.loads(call.get("arguments", ""))
            schema = self._schemas.get(name)
            if (schema is None or not isinstance(arguments, dict)
                    or set(arguments) != set(schema["parameters"]["required"])
                    or any(not isinstance(value, str) for value in arguments.values())):
                raise ValueError
        except (TypeError, ValueError):
            message = "The requested action has invalid arguments; it was not executed."
            await self.tools._post_status(message)
            return {"ok": False, "message": message}
        key = (turn, name, json.dumps(arguments, sort_keys=True))
        if key in self._attempts:
            return {**self._attempts[key], "repeat": True}
        # Reserve before making an external request, including uncertain outcomes.
        self._attempts[key] = {"ok": False, "message": "Action already attempted; do not retry."}
        try:
            message = await getattr(self.tools, name)(**arguments)
            result = {"ok": True, "message": message}
        except ToolError as error:
            result = {"ok": False, "message": str(error)}
        self._attempts[key] = result
        return result
