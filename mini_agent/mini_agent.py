#!/usr/bin/env python3
"""
Mini Agent - a coding agent built on Claude Code CLI.

Architecture: LLM (Claude Code) + Loop (ours) + Tools (ours)
Claude Code is used as the LLM backend via `claude -p` with all
built-in tools disabled. We define our own tools, manage the
conversation loop, and execute tool calls locally.

Based on: https://ampcode.com/notes/how-to-build-an-agent
"""

import json
import os
import subprocess
import sys
import uuid

# ---------------------------------------------------------------------------
# System prompt - teaches Claude our tool-calling protocol
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a coding agent that helps users read, understand, and edit code.

You have access to tools to interact with the local filesystem. Use them as needed to accomplish the user's task.

## Tool calling protocol

When you need to use a tool, respond with ONLY a JSON object in this exact format - no other text:
{"tool_call": {"name": "tool_name", "input": {parameters}}}

When you are done and ready to respond to the user, respond with normal text (no JSON).

You may call one tool at a time. After each tool call you will receive the result, then you can decide what to do next - call another tool or respond.

## Available tools

1. read_file
   Read the contents of a file.
   Input: {"path": "string - absolute or relative file path"}

2. list_files
   List files and directories at a path. Directories have a trailing /.
   Input: {"path": "string - directory path"}

3. edit_file
   Edit a file by replacing an exact string match (first occurrence only).
   Input: {
     "path": "string - file path",
     "old_str": "string - exact text to find",
     "new_str": "string - replacement text"
   }

## Guidelines

- Read files before editing so you know exactly what to replace.
- Use list_files to explore directories when you need context.
- Be precise with old_str - it must match the file contents exactly.
- When you are finished, explain what you did in plain text.
"""

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def tool_read_file(inp):
    path = inp["path"]
    if not os.path.isfile(path):
        return f"Error: {path} is not a file or does not exist."
    with open(path) as f:
        return f.read()


def tool_list_files(inp):
    path = inp.get("path", ".")
    if not os.path.isdir(path):
        return f"Error: {path} is not a directory or does not exist."
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        entries.append(name + "/" if os.path.isdir(full) else name)
    return "\n".join(entries) if entries else "(empty directory)"


def tool_edit_file(inp):
    path = inp["path"]
    old_str = inp["old_str"]
    new_str = inp["new_str"]

    if not os.path.isfile(path):
        return f"Error: {path} does not exist."

    with open(path) as f:
        content = f.read()

    if old_str not in content:
        return f"Error: old_str not found in {path}."

    updated = content.replace(old_str, new_str, 1)
    with open(path, "w") as f:
        f.write(updated)

    return f"OK: edited {path}"


# Tool registry - maps names to callables
TOOLS = {
    "read_file": tool_read_file,
    "list_files": tool_list_files,
    "edit_file": tool_edit_file,
}

# ---------------------------------------------------------------------------
# Claude Code CLI wrapper
# ---------------------------------------------------------------------------


def call_claude(prompt, session_id, system_prompt=None):
    """Call Claude Code in non-interactive mode and return parsed JSON."""

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--tools", "",            # disable all built-in tools
        "--session-id", session_id,
    ]

    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"Claude CLI error:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # If JSON parsing fails, return the raw text
        return {"result": result.stdout.strip(), "session_id": None}


# ---------------------------------------------------------------------------
# Parse a tool call from Claude's response text
# ---------------------------------------------------------------------------


def parse_tool_call(text):
    """Try to extract a tool_call JSON from the response text.

    Returns (name, input_dict) or None if no tool call found.
    """
    text = text.strip()

    # Try parsing the entire response as JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "tool_call" in parsed:
            tc = parsed["tool_call"]
            return tc["name"], tc["input"]
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Sometimes Claude wraps tool calls in markdown code fences
    for fence in ["```json", "```"]:
        if fence in text:
            start = text.index(fence) + len(fence)
            end = text.index("```", start)
            block = text[start:end].strip()
            try:
                parsed = json.loads(block)
                if isinstance(parsed, dict) and "tool_call" in parsed:
                    tc = parsed["tool_call"]
                    return tc["name"], tc["input"]
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

    return None


# ---------------------------------------------------------------------------
# Execute a tool call
# ---------------------------------------------------------------------------


def execute_tool(name, inp):
    """Look up and execute a tool by name. Returns the result string."""
    if name not in TOOLS:
        return f"Error: unknown tool '{name}'"
    try:
        return TOOLS[name](inp)
    except Exception as e:
        return f"Error executing {name}: {e}"


# ---------------------------------------------------------------------------
# The agent loop
# ---------------------------------------------------------------------------

MAX_TOOL_CALLS = 20  # safety limit


def run_agent(user_prompt, session_id, is_first_prompt=False):
    """Run the agent loop: prompt -> tool calls -> final response."""

    prompt = user_prompt
    tool_calls = 0

    print()  # blank line before agent output

    while True:
        # Send system prompt only on the very first call of the session
        send_system = SYSTEM_PROMPT if (is_first_prompt and tool_calls == 0) else None

        # Call Claude Code
        response = call_claude(
            prompt,
            session_id=session_id,
            system_prompt=send_system,
        )

        text = response.get("result", "")

        # Check for a tool call
        tool_call = parse_tool_call(text)

        if tool_call:
            name, inp = tool_call
            tool_calls += 1
            print(f"  [{tool_calls}] {name}({json.dumps(inp)})")

            if tool_calls > MAX_TOOL_CALLS:
                print("\n  Hit tool call limit. Stopping.")
                break

            # Execute and feed result back
            result = execute_tool(name, inp)

            # Truncate huge results to keep context manageable
            if len(result) > 10000:
                result = result[:10000] + "\n... (truncated)"

            prompt = f"Tool result for {name}:\n{result}"
            continue

        # No tool call - final response
        print(f"Agent: {text}")
        break

    return session_id


# ---------------------------------------------------------------------------
# Main - interactive REPL or single-shot
# ---------------------------------------------------------------------------


def main():
    session_id = str(uuid.uuid4())

    if len(sys.argv) > 1:
        # Single-shot: pass prompt as argument
        user_prompt = " ".join(sys.argv[1:])
        run_agent(user_prompt, session_id, is_first_prompt=True)
    else:
        # Interactive REPL
        print("Mini Agent v0.5 (type /exit to quit)")
        print("-" * 40)
        first = True
        while True:
            try:
                user_input = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit", "q", "/exit"):
                print("Bye.")
                break

            run_agent(user_input, session_id, is_first_prompt=first)
            first = False


if __name__ == "__main__":
    main()
