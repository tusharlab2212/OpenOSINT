---
title: "Use OpenOSINT as an MCP server"
label: "MCP server"
seo_title: "OpenOSINT MCP server for Claude Desktop and Claude Code"
description: "Run openosint-mcp from a checkout of this fork with uv in Claude Desktop, Claude Code, Cursor or any MCP client. Config, API keys, active tools."
group: Use
order: 5
---
The MCP server exposes the OpenOSINT tools to any [Model Context Protocol](https://modelcontextprotocol.io/) client over stdio. The client's own model drives the tools; OpenOSINT only runs them and returns real output.

## Requirements

Install [uv](https://docs.astral.sh/uv/) and clone this fork (`git clone https://github.com/tusharlab2212/OpenOSINT`). Every client then runs the server from that checkout, with dependencies installed from its `uv.lock`:

```bash
uv run --locked --project /absolute/path/to/OpenOSINT openosint-mcp
```

This repository is a fork of OpenOSINT. `uvx --from openosint openosint-mcp` and `pip install openosint` install the **upstream** release from PyPI instead, which does not have this fork's changes: it rejects `--allow-active-agent`, for example. If you installed this fork with `pip install -e .`, the executable is `openosint-mcp`.

## Claude Code

```bash
claude mcp add openosint -- uv run --locked --project /absolute/path/to/OpenOSINT openosint-mcp
claude mcp list
```

Add API keys with `-e` flags before the `--`:

```bash
claude mcp add openosint -e SHODAN_API_KEY=your-key -e HIBP_API_KEY=your-key -- uv run --locked --project /absolute/path/to/OpenOSINT openosint-mcp
```

## Claude Desktop

Edit `claude_desktop_config.json` and restart the app. On macOS it is at `~/Library/Application Support/Claude/`, on Windows at `%APPDATA%\Claude\`.

```json
{
  "mcpServers": {
    "openosint": {
      "command": "uv",
      "args": ["run", "--locked", "--project", "/absolute/path/to/OpenOSINT", "openosint-mcp"],
      "env": {
        "SHODAN_API_KEY": "your-key"
      }
    }
  }
}
```

## Cursor and other clients

Any client that can launch a stdio MCP server takes the same command and arguments. For Cursor, put the JSON above in `~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project).

Desktop apps often start with a minimal `PATH` that does not include `uv`. If the server fails to start, replace `"uv"` with the absolute path printed by `which uv` (macOS, Linux) or `where uv` (Windows).

## API keys

Put keys in the client's `env` block, as above. OpenOSINT does not read a `.env` from the working directory the client starts it in. To use a file, point to it:

```json
"env": { "OPENOSINT_ENV_FILE": "/absolute/path/to/.env" }
```

Some variables are ignored in a file, `OPENOSINT_ALLOW_ACTIVE` among them; put those in the `env` block itself. See [What a file may not set](/docs/configuration/#what-a-file-may-not-set).

The [configuration page](/docs/configuration/) lists every key and which tools need it.

## Passive tools only, by default

`tools/list` returns only the passive tools, so the client's model never sees the noisy ones. Each tool description carries its noise label. Every MCP call is chosen by the client's model, so exposing the tools that touch the target or are noisy takes two separate opt-ins, both required:

- append `--allow-active --allow-active-agent` after `openosint-mcp`;
- or set `OPENOSINT_ALLOW_ACTIVE=1` and `OPENOSINT_ALLOW_ACTIVE_AGENT=1` in the `env` block.

With only the first, active tools stay hidden and a call to one returns `blocked_for_model`. Read the [noise table and the section on model-chosen tools](/docs/safety/) before you enable both.

The server does not cap how many tools your client calls. Only `investigate_multi`, which runs several targets at once, shares one budget of %%MAX_CALLS_MULTI%% calls by default.

## Pin a version

Pin the checkout itself: `git checkout <commit>` in your clone runs exactly that commit of this fork, and `--locked` keeps its dependencies at the versions in its `uv.lock`. A PyPI version pin (`uvx --from openosint==%%VERSION%% …`) selects an upstream release, not this fork.

## Example prompt

```text
Investigate example.com. Check its DNS and email authentication, then its registration.
```
