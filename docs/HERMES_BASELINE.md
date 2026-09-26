# Hermes Agent Baseline Audit & Verification Report

**Document:** `docs/HERMES_BASELINE.md`  
**Baseline Date:** 2026-09-26  
**Audited Directory:** `D:\AI_Trading\hermes-agent`  
**Reference Directory:** `C:\Users\Administrator\AppData\Local\hermes\hermes-agent` (Read-only reference)

---

## 1. Upstream Repository Baseline

| Parameter | Recorded Baseline Value |
|---|---|
| **Repository URL** | `https://github.com/NousResearch/hermes-agent.git` |
| **Cloned Location** | `D:\AI_Trading\hermes-agent` |
| **Branch** | `main` |
| **Commit Hash** | `d0288be5b3330d2442e3907185b8e9d0958297bb` |
| **Commit Date** | `2026-09-26 03:51:55 +0000` |
| **Commit Author** | `hermes-seaeye[bot] <307254004+hermes-seaeye[bot]@users.noreply.github.com>` |
| **Commit Subject** | `fmt(js): npm run fix on merge (#123423)` |
| **Declared Version** | `0.0.0` (in `pyproject.toml`), `1.0.0` (in `package.json`), installed reference binary `0.20.0` |
| **License** | MIT License (`LICENSE`) |

---

## 2. Environment & Runtime Requirements

### Python Runtime
- **Supported Range:** `>=3.11, <3.15` (declared in `pyproject.toml`).
- **Installed System Python:** `Python 3.13.11` (`C:\Program Files\Python313\python.exe`).
- **Reference Hermes Venv Python:** `Python 3.11.15` (`C:\Users\Administrator\AppData\Local\hermes\hermes-agent\venv`).
- **Core Pinned Dependencies:**
  - `openai==2.24.0`
  - `certifi==2026.5.20`
  - `truststore==0.10.4`
  - `python-dotenv==1.2.2`
  - `fire==0.7.1`
  - `httpx[socks]==0.28.1`
  - `rich==14.3.3`
  - `tenacity==9.1.4`
  - `ruamel.yaml==0.18.16`
  - `requests==2.33.0`
  - `jinja2==3.1.6`

### Node.js & Web Runtime
- **Node Version:** `v24.18.0` (`C:\Program Files\nodejs\node.exe`).
- **npm Version:** `12.0.2` (`C:\Program Files\nodejs\npm.ps1`).
- **Monorepo Workspaces:** `apps/*`, `ui-tui`, `ui-tui/packages/*`, `web`, `tests-js`.

---

## 3. Hermes Core Architecture Breakdown

### 3.1 Application Entry Points
1. **`cli.py`**:
   The primary command-line dispatcher (`hermes` command). Parses flags (`--oneshot`, `--model`, `--provider`, `--skills`, `--toolsets`, `--yolo`) and exposes key subcommands:
   - `hermes chat`: Interactive REPL session.
   - `hermes -z <prompt>`: One-shot non-interactive execution for scripting.
   - `hermes setup` / `hermes config`: Configuration management.
   - `hermes mcp`: MCP server management.
   - `hermes skills`: Skills management and discovery.
   - `hermes serve`: Headless backend server.
   - `hermes tui`: Modern Terminal UI.
   - `hermes gateway`: Messaging gateway.
2. **`run_agent.py`**:
   Low-level entrypoint that initializes agent instances, resolves toolsets, builds the initial system prompt, and launches the conversation loop.
3. **`mcp_serve.py`**:
   Runs Hermes as an MCP server, exposing agent capabilities to external systems over standard I/O.
4. **`tui_gateway/server.py`**:
   WebSocket server providing bi-directional telemetry and control between the Python agent core and the TypeScript UI.

### 3.2 Agent Loop Architecture (`agent/`)
- **`agent/conversation_loop.py`**: The heartbeat of Hermes. Orchestrates sequential turns:
  1. Compaction check (`context_compressor.py`).
  2. Prompt building (`prompt_builder.py`, `system_prompt.py`).
  3. LLM API call (`turn_api_call.py`).
  4. Response validation and tool parsing (`turn_tool_round.py`).
  5. Tool execution (`tool_executor.py`).
  6. Final response delivery (`turn_final_response.py`).
- **Turn Guardrails (`agent/tool_guardrails.py`)**: Detects repetitive tool failures, empty responses, and non-progress loops.
- **Context Compaction (`agent/context_compressor.py`, `agent/conversation_compression.py`)**: Prunes older messages while preserving system prompts, pinned context, and tool schemas.

### 3.3 Model & Provider Architecture (`agent/` and `plugins/model-providers/`)
- **Provider Base:** `agent/provider_base.py` defines standard abstract interface for completions, streaming, and embeddings.
- **Provider Registry:** `agent/provider_registry.py` and `agent/credential_pool.py` handle multi-key credential pooling, cooldowns on rate-limit (429), and failover.
- **Extensible Providers (`plugins/model-providers/`)**:
  - `gemini`: Native Google GenAI integration (`gemini_native_adapter.py`, `gemini-flash-latest`, `gemini-pro`).
  - `openrouter`: Router for multi-model access.
  - `anthropic`: Claude 3.5 / 3.7.
  - `openai-codex` / `openai`: OpenAI GPT-4o / O-series.
  - `deepseek`, `fireworks`, `nvidia`, `bedrock`, `custom`.

### 3.4 MCP (Model Context Protocol) Engine
- Located in `tools/mcp_tool.py`, `tools/mcp_stdio_watchdog.py`, and `tools/mcp_schema_cache.py`.
- Supports standard `stdio` and `sse` transports.
- Dynamic tool discovery, input validation, execution timeouts, and automatic restart on crash.

### 3.5 Browser & Computer-Use Capabilities
- **`tools/browser_tool.py`**: Integrates browser automation backends (local Chromium, Browserbase, Browser-Use).
- **`tools/browser_cdp_tool.py`**: Direct Chrome DevTools Protocol interaction.
- **`tools/computer_use_tool.py`**: Desktop GUI control (mouse, keyboard, window focus) interfacing with `cua-driver`.
- **`agent/vision_message_prep.py` & `tools/vision_tools.py`**: Prepares screenshots and multi-modal image inputs for vision-capable LLMs.

### 3.6 Skills Framework (`tools/skill_manager_tool.py`, `skills/`)
- Markdown-based skills (`SKILL.md`) with YAML frontmatter specifying:
  - `name`, `description`, `version`, `author`, `metadata`.
- Triggered dynamically when the system prompt includes relevant skill descriptions.
- Supports progressive context loading: compact frontmatter in index, deep instructions loaded on demand.

### 3.7 Memory Architecture (`agent/memory_manager.py`, `agent/curator.py`)
- SQLite-backed state store (`state.db`, `projects.db`).
- Short-term session memory vs. long-term persistent memories (`~/.hermes/memories/` or custom root).
- Background curator periodically extracts, consolidates, and indexes user preferences and workflow lessons.

### 3.8 Configuration Architecture (`hermes_yaml.py`, `hermes_constants.py`, `hermes_state.py`)
- Configured via YAML (`config.yaml`) with schema validation via `ruamel.yaml`.
- Environment variable overrides (`HERMES_MODEL`, `HERMES_PROVIDER`, `HERMES_REASONING`).
- Secrets managed through `.env` files with automatic redaction from logs and model prompts (`agent/redact.py`).

---

## 4. Baseline Test Suite Audit

- **Test Framework:** `pytest` + `pytest-asyncio`.
- **Test Locations:** `tests/` (Python), `tests-js/` (JavaScript/TypeScript).
- **Audit Findings:**
  - Running pytest directly against system Python 3.13 without an isolated virtual environment reveals that Hermes strictly requires its pinned dependencies (e.g. `ruamel.yaml==0.18.16`, `openai==2.24.0`, etc.).
  - The upstream repository is clean and uncorrupted at commit `d0288be5b3330d2442e3907185b8e9d0958297bb`.
  - For our standalone product (`nifty-autonomous-trader`), a clean isolated virtualenv must be created rather than polluting or reusing existing environments.

---

## 5. Architectural Assessment: Extension vs. Fork

| Aspect | Destructive In-Tree Fork | Clean Extension Layer (Recommended) |
|---|---|---|
| **Upstream Upgradability** | Extremely difficult; high merge conflicts with upstream commits. | **High; upstream updates can be pulled cleanly via git rebase/submodule.** |
| **Maintainability** | Fragile; changes scattered across upstream files. | **Clean; trading modules reside in their own dedicated namespace.** |
| **Security & Auditing** | Difficult to distinguish Hermes changes from trading changes. | **Clear separation of concerns; all trading logic is explicitly traceable.** |

**Decision:** Adopt an **Extension Layer Architecture**. The trading system will run as a specialized product sitting on top of the clean, uncorrupted Hermes engine.
