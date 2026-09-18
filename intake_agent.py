"""The intake agent: a Claude tool-use loop that drives the Opal tools service over HTTP.

It learns the tools from GET /discovery, the same way Opal would, then loops until Claude stops asking for tools.

Usage: uv run python intake_agent.py "your experiment idea in plain language"
"""

import json
import os
import sys

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

TOOLS_URL = os.environ.get("TOOLS_URL", "http://localhost:8080").rstrip("/")
MODEL = os.environ.get("INTAKE_MODEL", "claude-sonnet-5")
MAX_ITERATIONS = 8  # guardrail: a normal run needs 2 to 3 tool rounds

SYSTEM_PROMPT = """You are an experiment intake agent for a product experimentation team.
You receive a raw experiment idea in plain language. Your goal is to get it into the backlog
without creating duplicates.

Work like this:
1. Call list_experiment_backlog with no search_terms to see every open ticket.
2. Decide whether the idea duplicates or substantially overlaps an existing ticket
   (same page area and same kind of change, even if worded differently).
3. If it overlaps: call comment_on_experiment on that ticket, adding only the new angle
   this idea brings. Then stop. Do not file a new ticket.
4. If it is novel: structure it into a brief and call create_experiment_ticket.
   The hypothesis must read "Changing X will cause Y". If the idea does not state a
   primary metric, target page, or rationale, infer a sensible one and list that field
   name in inferred_fields. Never silently fill a gap.
5. Finish with a short report: what you did, which ticket, and why."""


def load_tools() -> tuple[list[dict], dict[str, str]]:
    """Turn the Opal discovery document into Claude tool definitions, plus a name -> endpoint map."""
    discovery = httpx.get(f"{TOOLS_URL}/discovery", timeout=30).json()
    tools, endpoints = [], {}
    for fn in discovery["functions"]:
        properties, required = {}, []
        for p in fn["parameters"]:
            properties[p["name"]] = p.get("schema") or {
                "type": p["type"],
                "description": p["description"],
            }
            if p["required"]:
                required.append(p["name"])
        tools.append({
            "name": fn["name"],
            "description": fn["description"],
            "input_schema": {"type": "object", "properties": properties, "required": required},
        })
        endpoints[fn["name"]] = fn["endpoint"]
    return tools, endpoints


def call_tool(endpoint: str, arguments: dict) -> tuple[str, bool]:
    """POST to the tool endpoint the same way Opal does: arguments wrapped in "parameters"."""
    try:
        r = httpx.post(f"{TOOLS_URL}{endpoint}", json={"parameters": arguments}, timeout=60)
        r.raise_for_status()
        return r.text, False
    except httpx.HTTPError as e:
        return f"Tool call failed: {e}", True


def run(idea: str) -> None:
    client = Anthropic()
    tools, endpoints = load_tools()
    print(f"Discovered {len(tools)} tools at {TOOLS_URL}: {', '.join(endpoints)}\n")

    messages = [{"role": "user", "content": f"New experiment idea:\n\n{idea}"}]

    def ask():
        return client.messages.create(
            model=MODEL, max_tokens=2048, system=SYSTEM_PROMPT, tools=tools, messages=messages
        )

    response = ask()
    iterations = 0

    # THE LOOP: keep going as long as Claude keeps asking for tools.
    # There is no "if duplicate" branch in this code. Claude picks the next tool after
    # reading the backlog, so the branch happens in its decision, and the number of calls varies.
    while response.stop_reason == "tool_use" and iterations < MAX_ITERATIONS:
        iterations += 1
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type == "text" and block.text.strip():
                print(f"[thinking] {block.text.strip()}\n")
            if block.type == "tool_use":
                print(f"[step {iterations}] {block.name} {json.dumps(block.input)}")
                result, is_error = call_tool(endpoints[block.name], block.input)
                print(f"  -> {result[:200]}{'...' if len(result) > 200 else ''}\n")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                    "is_error": is_error,
                })

        messages.append({"role": "user", "content": tool_results})
        response = ask()

    if response.stop_reason == "tool_use":
        print(f"Stopped: hit the {MAX_ITERATIONS}-iteration guardrail before the agent finished.")
        return

    print("=== Agent report ===")
    print("".join(b.text for b in response.content if b.type == "text"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: uv run python intake_agent.py "your experiment idea"')
    run(" ".join(sys.argv[1:]))
