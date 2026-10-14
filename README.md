# Umbreliana Core — High-Load Asynchronous FinTech & Syndicate Engine

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-informational?style=flat-square&logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7-red?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-green?style=flat-square)](https://www.gnu.org/licenses/gpl-3.0)

Umbreliana Core is an asynchronous, high-concurrency Telegram backend engineered for complex virtual economies, cyber-syndicate warfare, real-time AML telemetry, automated banking, and low-latency transactional games. Built on Aiogram 3, asyncpg, and Redis, the engine guarantees strict ACID transaction semantics, deterministic crash recovery, and distributed concurrency protection.

---

## Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                                   Telegram API                                    |
+-----------------------------------------------------------------------------------+
                                         |
                                         | Long Polling / Updates
                                         v
+-----------------------------------------------------------------------------------+
|                             Aiogram 3 Pipeline Layer                              |
|  [Shutdown] -> [TournamentLock] -> [RateLimit] -> [AntiChannel] -> [BanCheck]    |
|               -> [Subscription] -> [ActivityTracker] -> [L10n]                   |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                        Redis 7 (Distributed State & Locks)                        |
|  - Distributed User Locks (user_lock:action:user_id)                              |
|  - Sliding Window Rate Limiting (spam_clicks:user_id)                             |
|  - Active Session State Tracking (active_game:user_id)                            |
|  - Media Album De-duplication (album_lock:media_group_id)                         |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                                 Handlers Router                                   |
|  +---------------------------+  +-----------------------------------------------+ |
|  | FinTech Core & AML        |  | Syndicate Cyberwarfare & Tech Trees           | |
|  | - P2P Transfers & Banking |  | - Multi-Node Clan Sieges                      | |
|  | - Heuristic AML Profiling |  |   * Gateway (GPU Power)                       | |
|  | - Collateral Debt Reaper  |  |   * Crypto Node (Capital Decryption)          | |
|  | - Dynamic Crypto Market   |  |   * Social Engineering (Phishing)             | |
|  | - Double-Entry Ledger     |  | - Tech Trees (Income, Cooling, Tax)           | |
|  +---------------------------+  +-----------------------------------------------+ |
|  +---------------------------+  +-----------------------------------------------+ |
|  | Chaos Engine & Events     |  | Concurrency-Safe Mini-Games                   | |
|  | - Global Chaos Loop       |  | - Crash, Crazy Wheel, Mines, Bomb, Squid      | |
|  | - Macroeconomic Shocks    |  | - Row-Level Database Locks (FOR UPDATE)       | |
|  | - Infra Self-Healing      |  | - Session-Bound Nonce Validation              | |
|  | - State Reconstruction    |  | - Zero Race-Condition Guarantee               | |
|  +---------------------------+  +-----------------------------------------------+ |
+-----------------------------------------------------------------------------------+
                                         |
                                         | asyncpg Connection Pool (min=5, max=30)
                                         v
+-----------------------------------------------------------------------------------+
|                           PostgreSQL 16 (Storage Engine)                          |
|  - Strict ACID Transactions (async with db.transaction())                         |
|  - Pessimistic Row-Level Locking (SELECT ... FOR UPDATE)                          |
|  - Atomic Upsert & Clamping (INSERT ... ON CONFLICT DO UPDATE)                    |
|  - Persistent Audit Ledger (audit_log, whale_logs, event_history)                 |
+-----------------------------------------------------------------------------------+
```

---

## Core Subsystems

### 1. FinTech Core & AML Heuristics
* Automated Security Profiling: Real-time heuristic evaluation detecting abnormal wealth velocity, P2P transit mixers, multi-account syndicates, and casino exploit patterns via algorithmic scoring (`analyze_player_strategy`).
* Smart Credit Enforcement: Automated background reaper (`debt_reaper`) monitoring loan collateral, calculating compounding risk penalties, seizing offshore liquid assets upon default, and enforcing debtor blacklists.
* Dynamic Valuation Engine: Algorithmic pricing model for gold and virtual cryptocurrency (UMC) adjusting dynamically to circulating supply, market liquidity velocity, and server-wide capitalization.
* Dual-Entry Audit Logging: Continuous immutable ledger recording (`audit_log` and `whale_logs`) capturing high-value transactions and state mutations for post-mortem forensics.

### 2. Syndicate Cyberwarfare & Tech Trees
* Multi-Node Siege Mechanics: Synchronized clan warfare protocol distributed across three defensive layers:
  * Server Gateway: Raw GPU mining power brute-force calculations.
  * Cryptographic Node: Communal capital buyout and dynamic decryption barriers.
  * Social Engineering: Coordinated multi-agent phishing vectors requiring synchronized participant actions.
* Research Laboratory: Modular tech trees (income multipliers, hardware cooling thresholds, tax exemptions) impacting hardware depreciation rates and economic yield across all syndicate members.

### 3. Chaos Engine & Event-Driven Subsystems
* Macroeconomic Anomalies: Automated background loops (`global_chaos_loop` and `global_event_monitor`) triggering server-wide economic shifts (hardware shortages, market flash crashes, power grid outages, tax adjustments, instant dividend airdrops).
* Resilient State Recovery: Fail-safe routines (`recover_from_hard_crash`, `rescue_all_assets`) that capture runtime capital allocations during ungraceful restarts, store snapshots in SSD persistence (`data/restart.json`), and automatically refund affected participants.
* Infrastructure Self-Healing: Proactive daemon (`infra_auto_healer`) continuously verifying Redis and PostgreSQL socket availability, automating driver re-initialization, and isolating faults without taking down the service.

### 4. Concurrency-Safe Mini-Games
* High-Frequency Game Engines: Real-time implementations of Crash multiplier curves, Crazy Wheel, Mines Grid, Bomb Tag, Squid Game, Roulette, Race, and Sector.
* Double-Spending Elimination: Execution strictly protected by row-level pessimistic database locks (`SELECT ... FOR UPDATE`), atomic balance clamping (`INSERT ... ON CONFLICT DO UPDATE`), and distributed Redis mutexes (`user_lock`, `active_game`), preventing race conditions, concurrent replay attacks, and duplicate balance deductions.

---

## Repository Structure

```
umbreliana-core/
├── core/                   # Core infrastructure, drivers, and middleware
│   ├── backuper.py         # Automated database snapshot and export manager
│   ├── bot_state.py        # Global lifecycle state and shutdown signals
│   ├── database.py         # PostgreSQL connection pool (asyncpg), migrations, queries
│   ├── l10n.py             # Internationalization and localization middleware
│   ├── middlewares.py      # Rate limiting, flood control, security filters
│   ├── redis_driver.py     # Redis client lifecycle, distributed locking, Memurai bridge
│   ├── system_tasks.py     # Self-healing, crash recovery, background reconciliation
│   └── triggers.py         # Interaction triggers and regex parsers
├── handlers/               # Modular Aiogram 3 routers
│   ├── admin/              # Management panels, economy adjustments, Eye of God audit
│   ├── economy/            # Transfers, loans, deposits, market, crypto exchange, gold
│   ├── events/             # Chaos engine, macroeconomic event listeners, global buffs
│   ├── games/              # Concurrency-safe games (Crash, Mines, Wheel, Bomb, etc.)
│   ├── syndicate/          # Clan warfare, multi-node sieges, GPU farms, tech trees
│   └── users/              # Profiles, quests, leaderboards, tutorial, localization
├── data/                   # Runtime data files, SQLite fallback caches, SQL backups
├── locales/                # Multi-language translation bundles (ru.json, en.json)
├── logs/                   # Rotating system and error logs (bot_errors.log)
├── tests/                  # Integration and unit test suite
│   └── test_core.py        # Database pooling, balance mutations, and AML audit tests
├── tourner/                # Isolated tournament engine with dedicated handlers and db
├── utils/                  # Auxiliary helpers and formatting routines
├── gram.py                 # Primary application entrypoint and scheduler orchestrator
├── validator.py            # Static AST syntax, import resolution, and integrity validator
├── requirements.txt        # Production dependency specifications
└── start.bat               # Windows watchdog runner with pre-flight AST validation
```

---

## Tech Stack

* Core Runtime: Python 3.11+ / Asynchronous IO (`asyncio`)
* Framework: Aiogram 3.x (Router dispatching, custom Middlewares, Filters)
* Primary Database: PostgreSQL 16 via `asyncpg` connection pool (min: 5, max: 30)
* Distributed Cache & Locks: Redis 7 (or Memurai on Windows)
* Task Scheduling: APScheduler (`AsyncIOScheduler`)
* Static Analysis: AST Static Code Validator (`validator.py`)
* Testing Framework: Pytest 8.x with `pytest-asyncio`
* Payments: Telegram Stars (`XTR`) API Integration

---

## Security & Architecture Decisions

* ACID Transactional Guarantees: All financial transfers, orderbook matches, auction bids, and clan treasury contributions execute strictly inside `async with db.transaction()` contexts.
* Pessimistic Concurrency Control: Financial records and critical market lots enforce row-level locking via `SELECT ... FOR UPDATE` to completely eliminate race conditions and double-spending across parallel event loops.
* Distributed Rate Limiting & TTL Eviction: User actions are throttled through Redis key counters with sliding time-to-live (TTL) expiration, preventing denial-of-service and macro automation.
* Fault Isolation & Graceful Degradation: The Redis driver incorporates automated fallback modes. If the caching layer experiences temporary socket timeouts, non-critical features degrade gracefully while financial integrity remains backed by PostgreSQL ACID transactions.

---

## Quick Start

### 1. System Requirements

* Python 3.11 or higher
* PostgreSQL 16+
* Redis 7+ (or Memurai for Windows environments)

### 2. Clone Repository

```bash
git clone https://github.com/blakedimm/umbreliana-core.git
cd umbreliana-core
```

### 3. Create and Activate Virtual Environment

On Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

On Windows:
```cmd
python -m venv venv
venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Create a `.env` file in the project root:

```env
TOKEN=your_telegram_bot_token
ADMIN_ID=1412940726
DATABASE_URL=postgresql://user:password@localhost:5432/bot_database
REDIS_URL=redis://localhost:6379/0
MODERATORS=8489556437, 1580552207
DRY_RUN=0
```

### 6. Run Pre-flight Static Validation

Verify code integrity, syntax, and dependency resolution before runtime:

```bash
python validator.py
```

### 7. Run Test Suite

Execute automated integration tests against the database layer:

```bash
pytest tests/ -v
```

### 8. Launch Engine

Run the primary application process:

```bash
python gram.py
```

On Windows, you can alternatively use the production watchdog runner:

```cmd
start.bat
```

---

## Author & License

* Author: [blakedimm](https://github.com/blakedimm)
* Specialization: Backend Architecture, High-Load Telegram Bots, System Software
* License: GNU General Public License v3.0 (GPL-3.0)
