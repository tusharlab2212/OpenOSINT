---
title: "Install OpenOSINT"
label: "Install"
seo_title: "Install OpenOSINT with pip, pipx, uv or Docker"
description: "Install this OpenOSINT fork from a checkout with uv run --locked (Python 3.10+) or Docker, then check it with openosint dns example.com. No API key."
group: Get started
order: 3
---
## This fork

This repository is a security-hardened fork of OpenOSINT. Install it from a checkout:

```bash
git clone https://github.com/tusharlab2212/OpenOSINT
cd OpenOSINT
uv run --locked openosint dns example.com
```

`uv run --locked` installs the exact dependency versions recorded in `uv.lock`; `pip install -e .` inside the checkout also works, without the lock. Every other method on this page except Docker installs the **upstream** release from PyPI, which does not contain this fork's changes (for example `--allow-active-agent`).

OpenOSINT needs **Python 3.10 or newer**. It starts with no API keys and no `.env` file; keyless tools work immediately.

## Upstream release and other ways to install

| Method | Command |
|---|---|
| pipx (isolated CLI) | `pipx install openosint` |
| uv, installed | `uv tool install openosint` |
| pip (upstream release) | `pip install openosint` |
| uv, no install (upstream release) | `uvx openosint web` |
| Upstream source | `git clone https://github.com/OpenOSINT/OpenOSINT.git`, then `pip install -e .` inside it |
| Docker | `docker compose up --build` from a source checkout; the web UI is then at `http://localhost:8080` |

With Docker, one-off commands run as `docker compose run --rm openosint email target@example.com --json`. Reports go to `./reports/`; the graph database and session history live in the `openosint-data` volume.

## Optional extras

In a checkout of this fork, add an extra with `uv run --locked --extra name openosint ...` (or `pip install -e ".[name]"`). For the upstream release it is `pip install "openosint[name]"`.

| Extra | Adds |
|---|---|
| `ollama` | Local models through Ollama |
| `openai` | Any OpenAI-compatible endpoint |
| `shodan`, `censys` | The Shodan and Censys API clients |
| `socks` | SOCKS proxy support |
| `graph` | The FollowTheMoney library for `.ftm` export (builds PyICU, needs libicu and a C++ compiler) |
| `graph-dedup` | Same-entity scoring for the graph (Python 3.11+) |

## External programs

Four tools call a separate program, which must be on your `PATH`. They are noisy or unverified, so they are off until you pass `--allow-active` (see [Safety](/docs/safety/)).

| Tool | Program | Install |
|---|---|---|
| `search_email` | holehe | `pip install holehe` |
| `search_username` | sherlock | `pip install sherlock-project` |
| `search_domain` | sublist3r | `pip install sublist3r` |
| `search_phone` | phoneinfoga | see its project page |

The Docker image already includes holehe, sherlock and sublist3r.

## Check that it works

```bash
openosint --help
openosint dns example.com
```

`--help` lists every command. The `dns` lookup needs no key and no AI provider; it prints the domain's records and its SPF and DMARC analysis. There is no `--version` flag: run `pip show openosint`, or look at the banner when you start the REPL.

## Next

[Run your first investigation](/docs/quickstart/).
