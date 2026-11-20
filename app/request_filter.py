"""Recognize direct requests and the standalone listening-resume command."""

import re

ADDRESS = re.compile(
    r"^\s*(?:(?:hey|hi|hello|ok|okay)[,\s]+)?"
    r"(?:assistant|open\s*ai\s+demo)\b[\s,;:.!?–—-]*",
    re.IGNORECASE,
)
RESUME = re.compile(r"(?:please\s+)?start\s+listening(?:\s+please)?[.!?]*", re.IGNORECASE)

# Control turns have chat feedback; suppress a model preamble before their tools.
CONTROL_REQUEST = re.compile(
    r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
    r"(?:(?:un)?mute(?:\s+yourself)?|(?:stop|start)\s+listening|"
    r"leave(?:\s+(?:(?:this|the)\s+)?(?:call|meeting))?)"
    r"(?:\s+please)?(?:[.!?]*$|\s+(?:and|then)\b)", re.IGNORECASE,
)
