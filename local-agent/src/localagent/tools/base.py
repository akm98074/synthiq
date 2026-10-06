"""Tool definitions shared by every connector.

Each tool declares a risk tier, and the policy engine (not the model) decides
from that tier whether the tool may run automatically:

  read   - looks at data, changes nothing           -> runs automatically
  draft  - creates something new and reviewable     -> runs automatically, logged
  write  - changes or sends something                -> needs approval (scopes allowed)
  danger - deletes, spends, submits                  -> needs approval every time
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Literal, Union

Tier = Literal["read", "draft", "write", "danger"]
TIERS: tuple[Tier, ...] = ("read", "draft", "write", "danger")


class ToolError(Exception):
    """A tool failed in a way the model should be told about."""


@dataclass
class ToolResult:
    content: str                 # what the model sees
    display: str                 # one-line summary for the UI
    data: Any = None             # structured payload for the UI
    ok: bool = True
    untrusted: bool = False      # written by other people (mail, chats, web): fenced + scanned

    def to_dict(self) -> dict:
        return {"ok": self.ok, "display": self.display, "content": self.content, "data": self.data}


Handler = Callable[[dict], Union[ToolResult, Awaitable[ToolResult]]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    tier: Tier
    connector: str
    handler: Handler
    summary: Callable[[dict], str]
    intents: tuple[str, ...] = ("task", "schedule", "computer_action")
    examples: list[str] = field(default_factory=list)
    # Optional per-call risk: e.g. pressing a "Delete" button is danger even if the tool is write.
    risk: Callable[[dict], Tier] | None = None

    def tier_for(self, args: dict) -> Tier:
        if self.risk is None:
            return self.tier
        t = self.risk(args)
        return t if TIERS.index(t) > TIERS.index(self.tier) else self.tier

    def spec(self) -> dict:
        """Ollama / OpenAI-style function spec."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"{self.description} [{self.tier}]",
                "parameters": self.parameters,
            },
        }

    async def run(self, args: dict) -> ToolResult:
        out = self.handler(args)
        if inspect.isawaitable(out):
            out = await out
        return out


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


def s(desc: str, **extra) -> dict:
    return {"type": "string", "description": desc, **extra}


def i(desc: str, **extra) -> dict:
    return {"type": "integer", "description": desc, **extra}


def validate_args(schema: dict, args: Any) -> dict:
    """Light JSON-schema check and coercion for tool arguments from a small model."""
    if not isinstance(args, dict):
        raise ToolError("Arguments must be a JSON object.")
    props: dict = schema.get("properties", {})
    out: dict = {}
    for key, spec in props.items():
        if key not in args or args[key] is None or args[key] == "":
            continue
        value = args[key]
        typ = spec.get("type")
        try:
            if typ == "integer":
                value = int(value)
            elif typ == "number":
                value = float(value)
            elif typ == "boolean":
                value = value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
            elif typ == "array":
                if isinstance(value, str):
                    value = [v.strip() for v in value.split(",") if v.strip()]
                if not isinstance(value, list):
                    raise ValueError
            elif typ == "string":
                value = value if isinstance(value, str) else str(value)
        except (TypeError, ValueError) as exc:
            raise ToolError(f"Argument '{key}' must be of type {typ}.") from exc
        if "enum" in spec and value not in spec["enum"]:
            raise ToolError(f"Argument '{key}' must be one of {spec['enum']}.")
        out[key] = value
    missing = [k for k in schema.get("required", []) if k not in out]
    if missing:
        raise ToolError(f"Missing required argument(s): {', '.join(missing)}.")
    return out


def parse_when(value: str, *, end_of_day: bool = False) -> datetime:
    """Parse an ISO-ish local date/time from the model ('2026-10-06T15:00', '2026-10-06')."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ToolError(
            f"Could not read the date/time '{value}'. Use ISO format like 2026-10-06T15:00."
        ) from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    if len(value.strip()) == 10 and end_of_day:
        dt = dt + timedelta(days=1) - timedelta(seconds=1)
    return dt


def offset_seconds(dt: datetime, now: datetime | None = None) -> int:
    return int((dt - (now or datetime.now())).total_seconds())


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%a %d %b %Y, %H:%M")


def pretty_when(value: str | None) -> str:
    """Human form of a model-supplied date for approval cards; falls back to the raw text."""
    if not value:
        return ""
    try:
        dt = parse_when(value)
    except ToolError:
        return value
    return dt.strftime("%a %d %b %Y") if len(value.strip()) == 10 else fmt_dt(dt)
