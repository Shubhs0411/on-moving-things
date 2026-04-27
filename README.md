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
Every agent call is traced. Every trace is scored against 29 ground-truth eval cases. The eval harness runs on-demand or in CI. Pass rate is visible in real time.

```
AgentTracer → traces_YYYYMMDD.jsonl
EvalHarness → evals/results/eval_TIMESTAMP.json
    29 cases × 6 categories × precision-scored
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
| Eval | Custom harness | 29 cases, keyword recall + citation recall + status accuracy |

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

# 4. Run full system checks (graph + FMCSA + docling + ingestion)
python demo/cli.py check

# 5. View LangGraph routing architecture
python demo/cli.py architecture

# 6. Run scripted demo (expanded query set)
python demo/cli.py demo

# 7. Run eval harness
python demo/cli.py eval

# 8. Start API server
uvicorn src.api.main:app --reload
# Docs at http://localhost:8000/docs
```

---

## CLI Commands (Full)

```bash
# Interactive shell with slash shortcuts
python demo/cli.py interactive

# One-shot system health checks (KB + graph + FMCSA + docling + ingestion)
python demo/cli.py check
python demo/cli.py check --run-query
python demo/cli.py check --strict

# Architecture view (LangGraph)
python demo/cli.py architecture
python demo/cli.py architecture --mermaid

# Scripted product demo
python demo/cli.py demo

# Single compliance query
python demo/cli.py query "Run a full safety check on DOT 2345678"

# Show system status dashboard
python demo/cli.py status

# Knowledge graph views
python demo/cli.py graph 2345678
python demo/cli.py graph 2345678 --mermaid

# Ingest text or PDF into knowledge base
python demo/cli.py ingest data/regulations/fmcsa_hos.md --category HOS
python demo/cli.py ingest /path/to/inspection.pdf --category INSPECTION

# Eval harness
python demo/cli.py eval
python demo/cli.py eval --category csa_scoring
python demo/cli.py eval --n 10

# Tip: eval now runs a preflight auth/model check and fails fast with a clear
# error if ANTHROPIC_API_KEY/model access is misconfigured.
```

### Interactive Shortcuts

```text
/help
/status
/graph 2345678
/arch
/exit
```

## Query Library (All 29 Eval-Backed Queries)

Use any of these with:

```bash
python demo/cli.py query "<QUERY>"
```

### Carrier Vetting

- Is carrier with DOT number 1234567 safe to use for a general freight shipment?
- Can I use DOT 2345678 for a hazmat shipment? They have a conditional safety rating.
- Run a safety check on Sunrise Freight Partners, DOT 3456789
- What is the compliance status of Blue Ridge Distribution Co, DOT 4567890?
- Frontier Carriers (DOT 5678901) wants to haul for us. Should I be concerned about their controlled substances score?
- Use FMCSA inspection history for DOT 2345678 and tell me the top 3 CFR citations driving risk.

### Driver Qualification

- Is driver CDL-TX-001234 qualified to operate a Class A combination vehicle pulling a tanker?
- Check driver CDL-OH-005678. Can they drive today?
- Is CDL-FL-003456 eligible for safety-sensitive duties?
- What are the DQ file requirements for a new hire CDL driver under FMCSA rules?
- Driver CDL-NY-007890 wants to haul hazmat. Are they properly endorsed?

### CSA Scoring

- DOT 2345678 has a vehicle maintenance score of 91.3. What does that mean and what should they do?
- Explain how CSA scores are calculated and what the intervention thresholds are.
- DOT 2345678 has an HOS score of 82.1. What violations are likely driving this and how do we fix it?
- How does DOT 1234567's vehicle maintenance score of 58.3 compare to the threshold?
- What is the crash indicator BASIC and how is it different from other BASICs?
- DOT 2345678 has repeated brake and HOS violations from recent inspections. Give a 30-day corrective action plan.

### Regulation Lookup

- How many hours can a property-carrying driver drive in a day before they need to stop?
- When is a driver required to take a 30-minute rest break?
- What are the ELD exemptions? Which drivers don't need an ELD?
- What is the minimum liability insurance requirement for a dry van carrier hauling general freight?
- How does the 34-hour restart work? What are the requirements?
- What is the sleeper berth provision and how does it work for splitting rest time?
- Which FMCSA rules are most relevant when a carrier shows false logs and controlled substance violations in inspections?

### Risk Assessment

- A new motor carrier applied to haul for us. They have 5 power units, no safety rating yet, and only 12 inspections. How should I evaluate their risk?
- What signals should a broker look at to vet a carrier quickly before tendering a load?
- A driver failed a pre-employment drug test 6 months ago at a different company. Can they drive for us now?

### Multi-Domain

- We're hiring a driver who has a Class A CDL expiring in 2 months, a medical cert that expired last week, and their Clearinghouse shows CLEAR. What's their compliance status?
- DOT 2345678 has a fatal crash, CSA alerts on 4 BASICs, and a conditional safety rating. Should I load them?

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

29 test cases across 6 domains:

| Domain | Cases | What's Tested |
|--------|-------|---------------|
| `carrier_vetting` | 6 | Operating authority, CSA alerts, inactive carriers, FMCSA inspection-derived risk |
| `driver_qualification` | 5 | CDL validity, Clearinghouse PROHIBITED, refused drug test, DQ file gaps |
| `csa_scoring` | 6 | BASIC thresholds, improvement plans, inspection-driven corrective actions |
| `regulation_lookup` | 7 | HOS limits, ELD exemptions, 34-hour restart, sleeper berth, inspection-linked citations |
| `risk_assessment` | 3 | New entrants, broker checklist, hiring risk scenarios |
| `multi_domain` | 2 | Combined safety, CSA, and qualification risk synthesis |

Scoring: `0.5 × keyword_recall + 0.2 × citation_recall + 0.15 × status_accuracy + 0.15 × risk_accuracy`  
Pass threshold: ≥ 0.60

```bash
# Run all 29 cases
python demo/cli.py eval

# Run just driver qualification cases
python demo/cli.py eval --category driver_qualification

# Run live evals through pytest (fails if pass rate < 0.60)
python -m pytest evals/test_eval_harness.py -v

# Optional knobs for pytest bridge
EVAL_MIN_PASS_RATE=0.80 EVAL_N_CASES=10 python -m pytest evals/test_eval_harness.py -v
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
│   │   └── test_cases.py         # 29 ground-truth eval cases
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
