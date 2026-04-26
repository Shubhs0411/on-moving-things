# FreightMind AI

**Multi-agent transportation compliance intelligence.**  
FMCSA · DOT · CSA · 49 CFR — answered in seconds, cited to the paragraph.

---

## What This Is

Every day, shippers, brokers, and carriers make decisions under pressure with incomplete information:
- *Is this carrier safe to use?*
- *Can this driver legally operate today?*
- *What's driving our CSA score up, and how do we fix it?*
- *What does 49 CFR 395.3(a)(1) actually say?*

FreightMind is a multi-agent AI system that answers those questions instantly, with citations, with reasoning shown, and with a feedback loop that knows whether the answers are right.

---

## The Three Systems

Directly mirroring the architecture described in *On Moving Things*:

### System of Understanding — The Eye
Regulations don't enter as data. They enter as PDFs, interpretive guidance, state variations, and compound rules that interact in non-obvious ways. FreightMind structures those fragments into a **semantic knowledge graph** (ChromaDB) over FMCSA HOS, Driver Qualification, CSA scoring, and operating authority rules. Every answer is grounded in retrieved regulatory text with CFR citations.

```
data/regulations/
├── fmcsa_hos.md          # 49 CFR Part 395 — Hours of Service
├── fmcsa_driver_qual.md  # 49 CFR Part 391 — Driver Qualification Files
├── csa_scoring.md        # CSA BASIC scoring methodology
└── operating_authority.md # 49 CFR Parts 365/387 — Authority & Insurance
```

### System of Velocity — The Limbs
Four specialist agents, composable tools, routed by a LangGraph state machine. A new agent can be added in an afternoon. The router runs in a single Claude call. The whole system is FastAPI endpoints.

```
User Query
    │
    ▼
Router (claude-sonnet-4-6, one call, classifies intent)
    │
    ├──► CarrierVettingAgent    — DOT lookup, CSA scores, crash history
    ├──► DriverQualAgent        — CDL, medical cert, Clearinghouse, DQ file
    ├──► CSAScoringAgent        — BASIC percentiles, improvement plans
    └──► ComplianceOracleAgent  — RAG over regulations, full CFR citations
    │
    ▼
Synthesizer (formats, ensures citations, adds urgency signal)
    │
    ▼
Response
```

### System of Continuous Improvement — The Nervous System
Every agent call is traced. Every trace is scored against 25 ground-truth eval cases. The eval harness runs on-demand or in CI. Pass rate is visible in real time.

```
AgentTracer → traces_YYYYMMDD.jsonl
EvalHarness → evals/results/eval_TIMESTAMP.json
    25 cases × 5 categories × precision-scored
```

---

## Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| LLM | Anthropic Claude (`claude-opus-4-7`, `claude-sonnet-4-6`) | Opus for deep regulation Q&A; Sonnet for speed/cost on routing and vetting |
| Agent orchestration | LangGraph 0.3+ | State machine for multi-agent routing, memory, conditional edges |
| Vector store | ChromaDB | Local-first, zero-infra, cosine similarity over regulatory chunks |
| API | FastAPI | REST endpoints, automatic OpenAPI docs |
| CLI | Rich + Typer | Conference-ready terminal demo |
| Data models | Pydantic v2 | Typed compliance domain entities |
| Observability | Custom JSONL tracer | Every tool call, token count, latency — persisted |
| Eval | Custom harness | 25 cases, keyword recall + citation recall + status accuracy |

---

## Quick Start

```bash
# 1. Install
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

# 3. Run interactive demo
python demo/cli.py interactive

# 4. Run scripted demo (5 queries, all agent types)
python demo/cli.py demo

# 5. Run eval harness
python demo/cli.py eval

# 6. Start API server
uvicorn src.api.main:app --reload
# Docs at http://localhost:8000/docs
```

---

## Demo Queries

These queries exercise every agent in the system:

```bash
# Carrier vetting — dangerous carrier
python demo/cli.py query "Run a safety check on DOT 2345678 before I tender a hazmat load."

# Driver qual — disqualified driver  
python demo/cli.py query "Check driver CDL-OH-005678. Can they drive today?"

# CSA improvement
python demo/cli.py query "DOT 2345678 has HOS score 82.1. What violations are driving this?"

# Regulation Q&A
python demo/cli.py query "How does the 34-hour restart work? What are the 1am-5am requirements?"

# Risk assessment
python demo/cli.py query "New carrier, 5 trucks, unrated, 12 inspections. How do I evaluate risk?"
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/compliance/query` | Main compliance Q&A endpoint |
| `POST` | `/v1/carrier/vet?dot_number=X` | Direct carrier vetting |
| `POST` | `/v1/driver/qualify?license_number=X` | Direct driver qualification check |
| `GET` | `/v1/observability/stats` | Real-time session metrics |
| `GET` | `/v1/observability/traces` | Recent agent traces |
| `POST` | `/v1/eval/run` | Run eval harness |
| `POST` | `/v1/knowledge/search` | Direct knowledge base search |

---

## Eval Harness

25 test cases across 5 domains:

| Domain | Cases | What's Tested |
|--------|-------|---------------|
| `carrier_vetting` | 5 | Operating authority, CSA alerts, inactive carriers, fatal crashes |
| `driver_qualification` | 5 | CDL validity, Clearinghouse PROHIBITED, refused drug test, DQ file gaps |
| `csa_scoring` | 5 | BASIC thresholds, improvement plans, root-cause analysis |
| `regulation_lookup` | 6 | HOS limits, ELD exemptions, 34-hour restart, sleeper berth, insurance minimums |
| `risk_assessment` | 4 | New entrants, multi-domain queries, broker checklist |

Scoring: `0.5 × keyword_recall + 0.2 × citation_recall + 0.15 × status_accuracy + 0.15 × risk_accuracy`  
Pass threshold: ≥ 0.60

```bash
# Run all 25 cases
python demo/cli.py eval

# Run just driver qualification cases
python demo/cli.py eval --category driver_qualification
```

---

## Project Structure

```
freightmind-ai/
├── src/
│   ├── models/domain.py          # Pydantic entities: Carrier, Driver, CSAScore, ComplianceReport
│   ├── knowledge/
│   │   ├── regulations.py        # Document loader + chunker
│   │   └── vectorstore.py        # ChromaDB: ingest, search, RAG context
│   ├── agents/
│   │   ├── base.py               # Agentic loop, tracing, tool dispatch
│   │   ├── compliance_oracle.py  # Regulatory Q&A (claude-opus-4-7)
│   │   ├── carrier_vetting.py    # Carrier safety checks
│   │   ├── driver_qual.py        # Driver qualification (49 CFR 391)
│   │   └── csa_scoring.py        # CSA BASIC interpretation
│   ├── graph/orchestrator.py     # LangGraph: router → agent → synthesizer
│   ├── eval/
│   │   ├── harness.py            # Scoring + persistence
│   │   └── test_cases.py         # 25 ground-truth eval cases
│   ├── observability/tracer.py   # JSONL tracing + session metrics
│   └── api/main.py               # FastAPI REST endpoints
├── data/
│   ├── regulations/              # FMCSA/DOT knowledge documents
│   └── mock/                     # Carrier + driver test fixtures
├── demo/cli.py                   # Rich terminal demo + CLI
├── evals/results/                # Eval run outputs
└── pyproject.toml
```

---

## Domain Coverage

- **Hours of Service (HOS):** 11-hour driving limit, 14-hour window, 60/70-hour rule, 34-hour restart, sleeper berth, ELD requirements and exemptions
- **Driver Qualification:** CDL classes/endorsements, medical certification, FMCSA National Registry, Drug & Alcohol Clearinghouse, DQ file requirements (49 CFR 391.51)
- **CSA Scoring:** All 7 BASICs, intervention thresholds, time-weighting, DataQs process, improvement planning
- **Operating Authority:** MC/DOT registration, SAFER lookup, insurance minimums by commodity type, new entrant requirements
- **Drug & Alcohol:** Pre-employment/annual Clearinghouse queries, prohibited status, Return-to-Duty process

---

## Design Principles

**Grounded, not hallucinated.** Every regulation answer is retrieved from the knowledge base before Claude responds. The system knows what it doesn't know.

**Composable.** Adding a new agent (e.g., HazMat specialist, insurance underwriting agent) requires one new file and two lines in the LangGraph graph.

**Observable.** Every call is traced. Latency, tokens, tool calls, errors — all visible. The eval harness runs on the same live system, not a mock.

**Direct.** The person asking these questions is making a real decision under pressure. The system gives a clear answer, not a hedge.

---

## Author

**Shubham Deshmukh**  
MS Computer Science, Virginia Tech  
[github.com/Shubhs0411](https://github.com/Shubhs0411) · [linkedin.com/in/shubhdesh](https://linkedin.com/in/shubhdesh)
