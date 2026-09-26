# NIFTY AUTONOMOUS TRADER — PACKAGING & INSTALLATION ARCHITECTURE

**Document:** `docs/PACKAGING_ARCHITECTURE.md`  
**Architecture Version:** 1.0.0 (Phase 0 Baseline)  
**Status:** Approved Packaging Design  

---

## 1. Product Independence & Standalone Philosophy

A core requirement of this project is that **NIFTY Autonomous Trader must be a standalone, self-contained software product**:
- It must **NEVER** depend upon, read, or modify the host machine's existing Hermes installation (`C:\Users\Administrator\AppData\Local\hermes\`).
- It must package its own isolated runtime, configuration files, SQLite databases, logs, and process managers.
- When installed on an end-user's computer, it runs out of the box without requiring manual developer configuration or external system environment variable hacking.

---

## 2. Directory Layout of Installed Product

```
C:\Program Files\NiftyAutonomousTrader\ (or %LOCALAPPDATA%\NiftyTrader\)
│
├── bin\
│   ├── nifty-trader.exe             # Application Launcher / CLI shim
│   └── nifty-daemon.exe             # Windows Service / Background worker
│
├── runtime\
│   ├── python\                      # Isolated Python 3.13 / 3.11 virtualenv
│   │   ├── Lib\site-packages\       # Pinned dependencies (openai, pydantic, yfinance)
│   │   └── Scripts\
│   └── node\                        # Node.js runtime for TUI / Puppeteer
│
├── core\
│   ├── hermes_engine\               # Clean Hermes Agent core runtime
│   ├── trader_engine\               # NIFTY Autonomous Trader extension modules
│   └── web_dashboard\               # Compiled static assets for UI
│
├── config\                          # User-editable configuration
│   ├── settings.yaml                # General trading & risk settings
│   ├── models.yaml                  # Model Router & AI provider routing
│   └── .env                         # Encrypted/secured API keys
│
├── data\                            # Persistent local databases
│   ├── trader.db                    # Candles, orders, positions, sessions
│   └── experience.db                # Post-mortems, mistake tags, strategy lab
│
└── logs\                            # Structured diagnostic & audit logs
    ├── trader.log                   # Human-readable operational log
    ├── events.jsonl                 # Machine-readable JSONL audit trail
    └── errors.log                   # Exception traces
```

---

## 3. Product CLI Control Suite

The application is controlled via a simple, intuitive command-line interface:

```bash
# Start the autonomous trading session in interactive console mode
nifty-trader start

# Start the agent as a background Windows daemon / service
nifty-trader daemon --start

# Check live trading state, current 15M/1H bias, active position, and daily PnL
nifty-trader status

# Open the local interactive browser dashboard (http://127.0.0.1:8765)
nifty-trader dashboard

# Gracefully pause the agent and complete existing candle wait
nifty-trader stop

# Emergency Kill-Switch: Immediately close all positions and shut down
nifty-trader kill

# Replay an arbitrary historical date in simulation mode
nifty-trader replay --date 2026-09-18
```

---

## 4. Installer & Distribution Strategy

### 4.1 Windows Installer Packaging
1. **Target Artifact:** `NiftyAutonomousTrader-Setup-v1.0.0.exe` built using **Inno Setup** or **PyInstaller / PyOxidizer**.
2. **Setup Wizard Steps:**
   - Detects or installs Microsoft Visual C++ Redistributable.
   - Creates isolated application directory in `%LOCALAPPDATA%\NiftyTrader\`.
   - Creates a dedicated virtual environment with exact pinned wheels.
   - Installs Chrome/Puppeteer browser binaries or registers system Chrome.
   - Prompts the user to securely input their AI API key (Gemini / OpenRouter).
   - Generates desktop shortcut and registers `nifty-trader` to user `PATH`.

### 4.2 Configuration & Secrets Management
- API keys (e.g. `GEMINI_API_KEY`, `OPENROUTER_API_KEY`) are stored in `config/.env`.
- Hermes internal redaction engine (`agent/redact.py`) is activated by default, ensuring that secret tokens never appear in terminal output, log files, or model context prompts.
- All configuration changes can be made either via the CLI (`nifty-trader config set model.provider gemini`) or through the interactive web dashboard.

### 4.3 Update & Telemetry Architecture
- **In-App Upgrader:** Queries product release manifest (`https://api.niftytrader.io/releases/latest.json` or private GitHub releases).
- **Atomic Rollback:** Updates are downloaded into a staging folder. If health checks fail during startup after an update, the loader automatically reverts to the previous working version.
- **Privacy Policy:** No trading strategy, account balance, or order data is ever transmitted to external servers. All data remains 100% local.
