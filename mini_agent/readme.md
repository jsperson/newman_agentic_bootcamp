# Mini Agent

A minimal coding agent built on Claude Code CLI. About 300 lines of Python, zero external dependencies.

Based on [How to Build an Agent](https://ampcode.com/notes/how-to-build-an-agent) by AmpCode, ported from Go to Python and adapted to use Claude Code as the LLM backend instead of direct API calls.

## Architecture

An agent is three things:

1. **An LLM** - Claude, via the Claude Code CLI
2. **A loop** - sends prompts, intercepts tool calls, executes them locally, feeds results back
3. **Tools** - Python functions that read, list, and edit files

Claude Code runs in non-interactive mode (`claude -p`) with all built-in tools disabled (`--tools ""`). A system prompt teaches Claude a JSON-based tool-calling protocol. Our Python code owns the conversation loop and executes all tool calls locally.

## How it works

### The conversation flow

```
User: "Add error handling to main.py"

Agent loop:
  -> sends prompt to Claude Code CLI (--session-id to create session)
  <- Claude responds: {"tool_call": {"name": "read_file", "input": {"path": "main.py"}}}
  -> agent executes read_file("main.py") locally
  -> sends file contents back to Claude (--resume to continue session)
  <- Claude responds: {"tool_call": {"name": "edit_file", "input": {...}}}
  -> agent executes the edit locally
  -> sends result back to Claude
  <- Claude responds with plain text explanation
  -> agent prints it and stops
```

### Session management

A UUID is generated once per session (at startup for REPL mode, or per invocation for single-shot mode). The first CLI call uses `--session-id` to create the session. All subsequent calls - both tool call follow-ups and new REPL prompts - use `--resume` to continue the same conversation. This gives Claude full context of everything that's happened in the session.

### Code walkthrough

**Imports (lines 13-17)** - All standard library. `json` for parsing responses and tool calls. `os` for filesystem operations. `subprocess` for calling the `claude` CLI. `sys` for args and stderr. `uuid` for generating session IDs.

**System prompt (lines 23-60)** - Replaces what the API's `tools` parameter normally does. Tells Claude three things: what it is (a coding agent), the protocol (output ONLY a JSON object for tool calls, plain text when done), and what tools exist (read_file, list_files, edit_file with parameter descriptions).

**Tool implementations (lines 67-112)** - Three plain functions:

- `tool_read_file` - takes a path, checks it exists, returns the contents
- `tool_list_files` - lists a directory sorted alphabetically, appends `/` to subdirectories
- `tool_edit_file` - reads a file, finds an exact string match, replaces the first occurrence, writes it back

The tool registry (line 108) is a dict mapping name strings to callables. This is where you add new tools - write the function, add an entry to the dict.

**CLI wrapper (lines 119-147)** - Builds and runs a `claude` command:

```bash
# First call - creates the session
claude -p "prompt" --output-format json --tools "" --session-id UUID --append-system-prompt "..."

# Subsequent calls - resumes the session
claude -p "prompt" --output-format json --tools "" --resume UUID --append-system-prompt "..."
```

Key flags:

- `-p` - non-interactive mode, print and exit
- `--output-format json` - structured JSON response
- `--tools ""` - disables all built-in tools, forcing Claude to use our protocol
- `--session-id UUID` - creates a session with a specific ID (first call only)
- `--resume UUID` - continues an existing session (all subsequent calls)
- `--append-system-prompt` - adds our tool-calling protocol on top of Claude Code's default context (sent on every call to prevent tool leakage on resumed sessions)

Returns parsed JSON. Falls back to wrapping raw text in a dict if parsing fails.

**Tool call parser (lines 155-185)** - Takes Claude's response text and determines if it's a tool call or a final answer. First tries parsing the whole response as JSON looking for `{"tool_call": {...}}`. If that fails, checks for markdown code fences (LLMs love wrapping JSON in these even when told not to). Returns `(name, input_dict)` for tool calls, `None` for final answers.

**Tool execution (lines 193-200)** - Looks up the tool name in the registry, calls it, returns the result. Wraps everything in try/except so a broken tool returns an error message instead of crashing the agent.

**The agent loop (lines 210-259)** - The core of the whole thing:

1. Determine whether to resume (all calls except the very first one in the session)
2. Call Claude Code with the prompt and system prompt (sent every call)
3. Parse the response - is it a tool call or a final answer?
4. If tool call: execute the tool, set the prompt to the tool result, loop back
5. If final answer: print it and break

Safety limit of 20 tool calls per prompt prevents runaway loops. Results over 10K characters get truncated to keep context manageable.

**Main entry point (lines 267-302)** - Generates a session UUID, then runs in one of two modes: single-shot (pass prompt as command-line args) or interactive REPL (run with no args, get a prompt loop with persistent session context). The UUID is generated once at startup and shared across all `run_agent` calls, so the REPL maintains full conversation continuity.

## Prerequisites

- Python 3.8+
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- No pip dependencies - stdlib only

## Usage

### Single-shot mode

Run from the directory you want the agent to work in (file paths are relative to cwd):

```bash
cd ~/my-project
python path/to/mini_agent.py "List the files here and describe what this project does"
```

### Interactive REPL

```bash
cd ~/my-project
python path/to/mini_agent.py
```

```
  ┌───────────────────────────┐
  │  Mini Agent  v0.9         │
  │  LLM + Loop + Tools       │
  │  /exit to quit            │
  └───────────────────────────┘

You: List the files in this directory
  [1] list_files({"path": "."})
Agent: Here are the files in the current directory...

You: What files did you just show me?
Agent: I showed you the following files...

You: /exit
Bye.
```

The REPL maintains session context, so Claude remembers previous prompts and tool results within the same session.

## Adding new tools

1. Write a function that takes an `inp` dict and returns a string:

```python
def tool_write_file(inp):
    path = inp["path"]
    content = inp["content"]
    with open(path, "w") as f:
        f.write(content)
    return f"OK: wrote {path}"
```

2. Add it to the `TOOLS` dict:

```python
TOOLS = {
    "read_file": tool_read_file,
    "list_files": tool_list_files,
    "edit_file": tool_edit_file,
    "write_file": tool_write_file,
}
```

3. Add the tool description to `SYSTEM_PROMPT` so Claude knows it exists.

## Known limitations

- **Single tool call per turn** - Claude calls one tool at a time, waits for the result, then decides what to do next. No parallel tool execution.
- **String-match editing** - `edit_file` uses exact string replacement. If the same string appears multiple times, it replaces the first occurrence, which may not be the intended one.
- **No undo** - file edits are written directly. Use version control.
- **Context window** - the full conversation history grows with each turn via session resumption. Very long sessions may hit limits.
