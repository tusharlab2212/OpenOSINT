---
title: "Configuration"
label: "Configuration"
seo_title: "OpenOSINT configuration: API keys and environment variables"
description: "Every OpenOSINT API key and environment variable, which tools need one, where settings live and the order they load in. Generated from the code."
group: Use
order: 7
---
OpenOSINT starts with zero configuration. A key is only needed by the tool that uses it, plus one AI provider if you use the chat or REPL.

## Where settings come from

Highest priority first. The first source to set a variable wins.

1. Real environment variables. This includes the `env` block of an MCP client and the variables Docker Compose passes in. Command-line flags such as `--allow-active` and `--proxy` act at this level too.
2. `config.env` in the data directory: `~/.openosint/config.env`, or `$OPENOSINT_HOME/config.env`. The web UI saves keys here with user-only permissions where the OS supports it.
3. One `.env` file: the file named by `OPENOSINT_ENV_FILE`, otherwise the `.env` next to the `openosint/` package folder. That second file only exists when you run OpenOSINT from a source checkout (a git clone); a `pip` or `uvx` install has none.

OpenOSINT does not read a `.env` from the directory you run it from, or from any parent directory. Such a file could come from a cloned repository, an unpacked archive or a shared folder, and would otherwise set your API keys, base URLs, proxies or active mode. When one is there, startup prints a single line, `[!] Not loading <path>`, saying how to use it on purpose. See [Using a `.env` file](#using-a-env-file).

OpenOSINT reads a `.env` in place and never copies it into `config.env` on its own. To copy settings on purpose, run `openosint config import` (optionally `--from PATH` and `--only KEY,KEY`). It copies the API keys and provider settings listed in the table below, lists their names, asks for confirmation (`--yes` when there is no terminal), never overwrites a value already in `config.env`, and leaves your `.env` untouched. It never prints values. Without `--from` it uses the `.env` that was loaded, otherwise the nearest `.env` in the current directory or a parent, the one OpenOSINT no longer loads.

If `config.env` and a `.env` hold different values for the same setting, `config.env` wins. Startup prints a warning that names both files and the settings, so a stale key in `config.env` cannot silently override the one you just changed in `.env`.

### What a file may not set

Both `config.env` and the `.env` file are filtered. A file cannot set the variables below, in any letter case; startup lists any it skipped, by name only (`[!] Ignored in <file>: …`). Set them as real environment variables, or use the matching command-line flag.

- Process and loader: `PATH`, `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONUSERBASE`, `BASH_ENV`, `ENV`, and any name starting with `LD_` or `DYLD_`.
- Proxies and TLS: `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `SSL_CERT_DIR`, `CURL_CA_BUNDLE`, `SSLKEYLOGFILE`.
- Anthropic client: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_CUSTOM_HEADERS`.
- Web UI exposure: `OPENOSINT_TRUSTED_PROXY`, `TRUSTED_PROXY`, `OPENOSINT_ALLOW_CLIENT_BACKEND`, `OPENOSINT_ALLOWED_BASE_URLS`, `OPENOSINT_ALLOW_REMOTE`, `OPENOSINT_ALLOWED_HOSTS`, `OPENOSINT_ALLOWED_ORIGINS`, `DEMO_ALLOWED_ORIGINS`, `OPENOSINT_PUBLISHED_BIND`.
- Model authorization: `OPENOSINT_ALLOW_ACTIVE_AGENT`. Nothing saves it to a file; set it in the real environment, or use `openosint-mcp --allow-active-agent`.
- Locations: `OPENOSINT_HOME`, `OPENOSINT_ENV_FILE`, `OPENOSINT_GRAPH_DB`.

`OPENOSINT_ALLOW_ACTIVE` is accepted from `config.env`, where the web UI's active-tools switch saves it, but not from a `.env` file. Use `--allow-active`, a real environment variable or the web UI switch.

`OPENOSINT_PROXY_URL` and `OPENAI_BASE_URL` can come from a file. When they do, startup names the file and shows only the host, never credentials, path or query.

For the MCP server, set the variables in the client's `env` block; see [MCP server](/docs/mcp/).

## API keys and tokens

This table is generated from the key catalog in the code, so it matches the version you install.

<!-- gen:config-keys -->

`openosint setup brightdata` walks through the Bright Data settings: it asks before opening the signup page, reads the token hidden, checks it by listing your zones, and can create the SERP API and Web Unlocker zones after an explicit yes. It saves what you confirm to `config.env` (user-only), never replaces a saved value without asking, and never calls the billable request endpoint. It needs an interactive terminal.

The Bright Data key and zones are created in the [Bright Data dashboard](%%BRIGHTDATA_LINK_DOCS%%) (a free tier is available). That is a referral link: OpenOSINT earns a commission if you sign up through it, at no extra cost to you.

These tools need no key: <!-- gen:keyless -->. Tools that are noisy or touch the target also need `--allow-active`; see the [tools reference](/tools/).

## Behaviour settings

| Variable | Default | Purpose |
|---|---|---|
| `OPENOSINT_ALLOW_ACTIVE` | off | `1` enables active tools. Same as `--allow-active`. Enough for direct CLI subcommands; when an AI model picks the tool (REPL, `multi`, web UI chat, MCP) it also needs `OPENOSINT_ALLOW_ACTIVE_AGENT`. |
| `OPENOSINT_ALLOW_ACTIVE_AGENT` | off | `1` lets a tool call chosen by an AI model run an active tool, on top of `OPENOSINT_ALLOW_ACTIVE`; without it such calls return `blocked_for_model`. `openosint-mcp --allow-active-agent` is the same. Real environment only: ignored in `config.env` and `.env` files. See [Safety](/docs/safety/#tools-chosen-by-an-ai-model). |
| `OPENOSINT_MAX_TOOL_RESULT_CHARS` | 20000 (min 1000) | Characters of each tool result shown to the model; longer output is cut with an explicit note. You still see the full output. |
| `OPENOSINT_MAX_TOOL_CALLS` | %%MAX_CALLS%% | Maximum calls per user request. |
| `OPENOSINT_MAX_TOOL_CALLS_MULTI` | %%MAX_CALLS_MULTI%% | One shared cap for `investigate_multi` across all targets. |
| `ANTHROPIC_MODEL` | `%%DEFAULT_MODEL%%` | Model requested from Anthropic. `OPENOSINT_MODEL` still works but is deprecated. |
| `OPENOSINT_HOME` | `~/.openosint` | Data directory: `config.env`, `graph.db`, session history. |
| `OPENOSINT_GRAPH_DB` | `$OPENOSINT_HOME/graph.db` | Overrides only the graph database path. |
| `OPENOSINT_ENV_FILE` | unset | Explicit path to a `.env` file. A bad path is an error. |
| `OPENOSINT_PROXY_URL` | unset | Upstream proxy (`http://`, `https://` or `socks5://`) for web-facing tools. `--proxy` overrides it. |
| `OPENOSINT_ALLOWED_HOSTS` | loopback names | Extra `Host` values the web UI accepts, comma-separated. |
| `OPENOSINT_ALLOWED_ORIGINS` | unset | Extra browser origins allowed to call `/api/*`. |
| `OPENOSINT_ALLOW_REMOTE` | off | `1` is the same as `--allow-remote` for `openosint web`. |
| `OPENOSINT_SETUP_TOKEN` | unset | Lets a non-loopback browser save keys, sent as `X-Setup-Token`. |
| `OPENOSINT_GDELT_WINDOW_HOURS` | 6 (max 24) | Hours of news the globe keeps in memory. |
| `OPENOSINT_GDELT_MAX_ARTICLES` | 30000 | Hard cap on stored news articles; oldest are dropped first. |
| `OPENOSINT_GDELT_USE_PROXY` | off | Route GDELT downloads through the proxy. |

A real environment variable always wins over a saved value, and the web UI says so when that happens. Several of these (`OPENOSINT_ALLOW_ACTIVE`, `OPENOSINT_ALLOW_ACTIVE_AGENT`, `OPENOSINT_HOME`, `OPENOSINT_GRAPH_DB`, `OPENOSINT_ENV_FILE`, `OPENOSINT_ALLOWED_HOSTS`, `OPENOSINT_ALLOWED_ORIGINS`, `OPENOSINT_ALLOW_REMOTE`) are ignored in a `.env` file; see [What a file may not set](#what-a-file-may-not-set).

## Using a `.env` file

Keep the file wherever you like and point OpenOSINT at it:

```bash
# /home/you/openosint.env
ANTHROPIC_API_KEY=sk-ant-...
SHODAN_API_KEY=your-key
```

```bash
export OPENOSINT_ENV_FILE="$HOME/openosint.env"
```

Use an absolute path: a path that does not exist is an error. Alternatively, copy the keys into `config.env` once with `openosint config import --from "$HOME/openosint.env"` and drop the file.

In a source checkout, a `.env` at the repository root (next to `pyproject.toml`) is also read, with no variable needed.

### Upgrading from a version that searched the working directory

Earlier versions loaded the first `.env` found by searching upward from the directory you ran `openosint` from. If your keys are in such a file, startup now prints `[!] Not loading <path>`. Do one of:

- run `openosint config import` in that directory: it offers that file, lists the keys and copies them to `config.env` after you confirm;
- set `OPENOSINT_ENV_FILE` to the file's absolute path;
- export the variables in your shell.

`config import` copies the API keys and provider settings from the table above. Other settings in the file, such as `ANTHROPIC_MODEL`, stay behind: keep the file and use `OPENOSINT_ENV_FILE`, or export them. A variable from [What a file may not set](#what-a-file-may-not-set), such as `HTTPS_PROXY` or `OPENOSINT_ALLOW_ACTIVE`, has to move to your shell or a command-line flag.
