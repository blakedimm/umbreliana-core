# ⚡️ Umbreliana Engine — High-Load Economic & Syndicate Core

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Aiogram](https://img.shields.io/badge/Aiogram-3.x-informational?logo=telegram&logoColor=white)](https://docs.aiogram.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-asyncpg-336791?logo=postgresql&logoColor=white)](https://github.com/MagicStack/asyncpg)
[![Redis](https://img.shields.io/badge/Redis-RateLimiting-red?logo=redis&logoColor=white)](https://redis.io/)

> ⚠️ **Status:** Production-Ready Core / Private Enterprise Architecture  
> **Umbreliana** is an asynchronous, high-concurrency Telegram backend engineered for complex virtual economies, cyber-syndicate warfare, automated banking, and real-time AML telemetry.

---

## 🚀 Key Modules & Architecture

### 1. 🛡 FinTech Core & AML Heuristics
* **Automated Security Profiling:** Real-time heuristic profiler detecting abnormal wealth velocity, P2P transit mixers, multi-account syndicates, and casino exploit patterns.
* **Smart Credit Enforcement:** Automated debt reaper monitoring borrower collateral, seizing offshore assets on default, and applying temporary blacklists.
* **Dynamic Valuation Engine:** Algorithmic gold and asset pricing based on circulating supply, market cooling velocity, and server-wide capitalization.

### 2. ⚔️ Syndicate Cyberwarfare & Tech Trees
* **Multi-Node Siege Mechanics:** Synchronized clan warfare across three defensive layers:
  * **Server Gateway:** Raw GPU mining power brute-force calculations.
  * **Cryptographic Node:** Communal capital buyout / dynamic decryption barriers.
  * **Social Engineering:** Coordinated multi-agent phishing actions.
* **Research Laboratory:** Modular tech trees impacting hardware efficiency, cooldowns, and tax exemptions for all clan members.

### 3. 🌪 Chaos Engine & Event-Driven Subsystems
* **Macroeconomic Anomalies:** Automated background loops generating global events (hardware shortages, market flash-crashes, regulatory raids, instant dividend airdrops).
* **Safe State Recovery:** Fail-safe routines resolving interrupted game loops and unfreezing capital during graceful restarts.

### 4. 🎰 Concurrency-Safe Mini-Games
* High-frequency engines (**Crash**, **Crazy Wheel**, **Mines Grid**, **Bomb Tag**, **Greed Dilemma**) with row-level database locking to eliminate race conditions and double-spending.

---

## 🛠 Tech Stack

* **Core Runtime:** Python 3.11+ / Asynchronous IO (`asyncio`)
* **Framework:** `aiogram 3.x` (Router-based dispatching, custom Middlewares)
* **Database & Pooling:** PostgreSQL via `asyncpg` with server-level tuning
* **Cache & Rate-Limiting:** Redis (sliding window / PX-based lock dropping)
* **Scheduling:** `APScheduler` (`AsyncIOScheduler`)
* **Payments:** Telegram Stars (`XTR`) API Integration

---

## ⚙️ Quick Start & Setup

### 1. Clone & Setup Environment
```bash
git clone [https://github.com/blakedimm/umbreliana-engine.git](https://github.com/blakedimm/umbreliana-engine.git)
cd umbreliana-engine
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Environment Variables (.env)
```env
TOKEN=your_telegram_bot_token
ADMIN_ID=your_telegram_id
DATABASE_URL=postgresql://user:password@localhost:5432/bot_database
REDIS_URL=redis://localhost:6379/0
DRY_RUN=0
```

### 3. Run Automated Tests
```bash
pytest tests/ -v
```

### 4. Launch Engine
```bash
python gram.py
```

---

## 🔒 Security & Data Integrity
* **ACID Transactions:** All financial operations, inventory exchanges, and marketplace buyouts execute inside strict `async with db.transaction()` blocks.
* **Memory Management:** Temporary session locks and anti-spam buffers automatically expire via Redis TTL keys.

---

## 👨‍💻 Author
* **Developer:** blakedimm
* **Specialization:** Backend Architecture, High-Load Telegram Bots, System Software
