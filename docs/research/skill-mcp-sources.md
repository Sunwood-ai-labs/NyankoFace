# Skill and MCP sample sources

Verified on 2026-07-14 against the public GitHub repositories owned by
[`Sunwood-ai-labs`](https://github.com/Sunwood-ai-labs).

The catalog intentionally uses real repositories rather than generated fixtures.
Skill candidates must contain a `SKILL.md`. MCP candidates must contain a server
implementation plus a package manifest or dependency file. Archived repositories
are excluded. A fork is allowed only when it is useful as a working MCP example and
is marked in the catalog.

## Skills

| Repository | Verification |
| --- | --- |
| [android-termux-ssh-bootstrap-skill](https://github.com/Sunwood-ai-labs/android-termux-ssh-bootstrap-skill) | Root `SKILL.md` |
| [cc-orchestrator-cli-skill](https://github.com/Sunwood-ai-labs/cc-orchestrator-cli-skill) | Root `SKILL.md` |
| [cities-skylines1-agent-skill](https://github.com/Sunwood-ai-labs/cities-skylines1-agent-skill) | Root `SKILL.md` |
| [draw-io-skill](https://github.com/Sunwood-ai-labs/draw-io-skill) | Root `SKILL.md` |
| [frontend-design-skill](https://github.com/Sunwood-ai-labs/frontend-design-skill) | Root `SKILL.md` |
| [gh-release-notes-skill](https://github.com/Sunwood-ai-labs/gh-release-notes-skill) | Root `SKILL.md` |
| [git-flow-skill](https://github.com/Sunwood-ai-labs/git-flow-skill) | Root `SKILL.md` |
| [jupytext-skill](https://github.com/Sunwood-ai-labs/jupytext-skill) | Root `SKILL.md` |
| [m5stack-arduino-cli-skill](https://github.com/Sunwood-ai-labs/m5stack-arduino-cli-skill) | Root `SKILL.md` |
| [repository-polish-skill](https://github.com/Sunwood-ai-labs/repository-polish-skill) | Root `SKILL.md` |

## MCP servers

| Repository | Verification |
| --- | --- |
| [aira-mcp-server](https://github.com/Sunwood-ai-labs/aira-mcp-server) | `package.json` and source tree |
| [command-executor-mcp-server](https://github.com/Sunwood-ai-labs/command-executor-mcp-server) | `package.json`, examples, and source tree |
| [discord-mcp](https://github.com/Sunwood-ai-labs/discord-mcp) | `package.json` and source tree |
| [duckduckgo-web-search](https://github.com/Sunwood-ai-labs/duckduckgo-web-search) | `package.json` and source tree |
| [github-kanban-mcp-server](https://github.com/Sunwood-ai-labs/github-kanban-mcp-server) | `package.json` and `src/server.ts` |
| [gitlab-kanban-mcp-server](https://github.com/Sunwood-ai-labs/gitlab-kanban-mcp-server) | `package.json` and source tree |
| [ideagram-mcp-server](https://github.com/Sunwood-ai-labs/ideagram-mcp-server) | `package.json` and `src/server.ts` |
| [mcp-voicevox](https://github.com/Sunwood-ai-labs/mcp-voicevox) | `pyproject.toml` and `src/mcp_server_voicevox/server.py`; upstream fork |
| [mcp-weather-service-server](https://github.com/Sunwood-ai-labs/mcp-weather-service-server) | `pyproject.toml` and `src/weather_service/server.py` |
| [source-sage-mcp-server](https://github.com/Sunwood-ai-labs/source-sage-mcp-server) | `package.json` and source tree |

The machine-readable import manifest is
[`seed/catalog/sunwood-ai-labs.json`](../../seed/catalog/sunwood-ai-labs.json).
