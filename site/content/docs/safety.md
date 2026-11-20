---
title: "Safety and responsible use"
label: "Safety"
seo_title: "OpenOSINT safety: passive mode, tool-call cap, noise labels"
description: "OpenOSINT is passive by default. How active tools are enabled, the per-request tool-call cap of %%MAX_CALLS%%, what each noise label means, and responsible use."
group: Reference
order: 9
---
OpenOSINT is built so that a default install does not touch your target and cannot run away with requests.

## Passive by default

In passive mode agents and MCP clients are only offered tools that query third-party data sources or compute locally. Tools that touch the target's infrastructure, or send many requests about it from your IP, are not just refused: they are not offered to the model at all, and an MCP client does not see them in `tools/list`. If a disabled tool is requested anyway, it returns a structured `disabled_in_passive_mode` result that says how to enable it.

Enable active tools only when you mean to. What you need depends on who picks the tool: you, with a direct command, or an AI model.

| Where | Who picks the tool | How to enable active tools |
|---|---|---|
| CLI subcommands (`openosint email …`, `username`, `scrape`) | you | `openosint --allow-active ...`, or `OPENOSINT_ALLOW_ACTIVE=1` |
| REPL and `openosint multi` | the AI model | `--allow-active` (or `OPENOSINT_ALLOW_ACTIVE=1`) **and** `OPENOSINT_ALLOW_ACTIVE_AGENT=1` |
| Web UI chat, server or browser keys | the AI model | Settings, "Enable active tools" (local installs only) **and** `OPENOSINT_ALLOW_ACTIVE_AGENT=1` in the server's environment |
| MCP server | the client's AI model | `openosint-mcp --allow-active --allow-active-agent`, or both variables in the client's `env` block |

A publicly reachable or demo web instance can never enable active tools, whatever its settings.

### Tools chosen by an AI model

A model reads tool output, and tool output comes from web pages, pastes and other sources anyone can write to. Text planted there can try to steer the model into running a tool on someone you never named (prompt injection). So `OPENOSINT_ALLOW_ACTIVE` alone does not let a model run an active tool: a call the model chose also needs the separate `OPENOSINT_ALLOW_ACTIVE_AGENT=1`. Without it, the call is refused with `blocked_for_model` and nothing is sent. This covers the REPL, `openosint multi`, the web UI chat, the browser-key chat, every MCP call and automatic pivoting (`investigate_graph`), and is enforced in the tool code itself, not only in the model's instructions. Direct CLI subcommands, where you type the target, are not affected. Set `OPENOSINT_ALLOW_ACTIVE_AGENT` only for sessions where you accept that a model, possibly steered by what it reads, decides which targets your active tools hit.

Every tool result a model receives is also marked as untrusted data inside clearly bounded markers, capped in size (`OPENOSINT_MAX_TOOL_RESULT_CHARS`, with an explicit note when output is cut), and the model is told never to follow instructions found in it. These measures reduce prompt injection; they do not eliminate it. A model can still be misled by what it reads, still choose passive lookups on identifiers it found in tool output (which sends those identifiers to third-party services), and still misreport a result. MCP results go back to your MCP client unwrapped, under the client's own handling of tool results.

## Tool-call cap

Each user request may spend at most `OPENOSINT_MAX_TOOL_CALLS` tool calls (default %%MAX_CALLS%%); every new message starts a fresh budget. `investigate_multi` shares one cap across all its targets (`OPENOSINT_MAX_TOOL_CALLS_MULTI`, default %%MAX_CALLS_MULTI%%). When the cap is reached the investigation stops with an explicit message and keeps the results so far.

## Noise labels

| Level | Meaning |
|---|---|
| passive | Queries third-party data sources or computes locally. Standard DNS lookups are the one indirect exception: they reach the target's nameservers through your resolver. |
| touches target | Makes requests the target's own infrastructure can see. |
| noisy | High request volume, or requests to many services about the target. Expect rate limits, blocks and possible alerts. |
| unverified | Network behaviour not yet confirmed with a traffic capture. Treated as non-passive. |
| inherits | A fan-out tool that only runs what the current mode allows. |

What each tool actually sends, generated from the code:

<!-- gen:noise -->

## Responsible use

- **Passive is not private.** Every service you query sees your search, and usually your API key or IP address. Treat lookups on Shodan, Have I Been Pwned, VirusTotal, Bright Data and similar services as visible to those providers.
- **Authorization.** Investigate only targets you are permitted to. Local laws on personal data differ; the legal and operational responsibility is yours. Read the [disclaimer](https://github.com/OpenOSINT/OpenOSINT/blob/main/DISCLAIMER.md).
- **Verify the output.** Tool results are real; the AI's reading of them is not proof, and text inside a result can be written to mislead it. Check a finding at its source before you act on it.
- **Stored personal data.** The optional [entity graph](/docs/entity-graph/) keeps data on your disk. You are its controller.
