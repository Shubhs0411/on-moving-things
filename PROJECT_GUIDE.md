# FreightMind AI — Project Guide

A deep dive into the architecture, data flow, components, and how to work with the system.

---

## Table of Contents

1. [What This Project Solves](#what-this-project-solves)
2. [High-Level Architecture](#high-level-architecture)
3. [Core Components Explained](#core-components-explained)
4. [Data Flow](#data-flow)
5. [The Four Agents](#the-four-agents)
6. [Knowledge Base](#knowledge-base)
7. [Evaluation System](#evaluation-system)
8. [File Structure & Key Files](#file-structure--key-files)
9. [How to Extend](#how-to-extend)

---

## What This Project Solves

### The Problem
Transportation compliance decisions happen under pressure with incomplete information:

```
Shipper/Broker makes decision:
  ├─ "Is this carrier safe?"
  ├─ "Can this driver work today?"
  ├─ "Why is our CSA score high?"
  ├─ "What does 49 CFR 395.3 say?"
  └─ All decisions have legal liability if wrong

Traditional approach:
  ├─ Manual FMCSA database lookup (slow)
  ├─ Read dense regulations (ambiguous)
  ├─ Call compliance officer (expensive)
  ├─ No audit trail
  └─ High risk of negligent selection claims
```

### The Solution
FreightMind AI answers these questions **instantly**, **with citations**, **with reasoning shown**:

```
User Query (natural language)
    ↓
System routes to appropriate specialist agent
    ↓
Agent retrieves relevant regulations (with CFR citations)
    ↓
Agent uses Claude to reason about facts + rules
    ↓
Response: Clear recommendation + evidence + sources
    ↓
Trace recorded for audit + evaluation
```

---

## High-Level Architecture

### The Three Systems

```
┌─────────────────────────────────────────────────────────────────┐
│  System of Understanding (The Eye)                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ChromaDB Vector Store                                   │   │
│  │ • HOS regulations (49 CFR 395)                          │   │
│  │ • Driver Qualification (49 CFR 391)                     │   │
│  │ • CSA Scoring methodology                               │   │
│  │ • Operating Authority rules (49 CFR 365/387)            │   │
│  │ • 30 regulatory chunks ingested + searchable            │   │
│  └─────────────────────────────────────────────────────────┘   │
│  Purpose: Grounded knowledge. Every answer is retrieved.        │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  System of Velocity (The Limbs)                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ LangGraph Orchestrator (State Machine Router)           │   │
│  │                                                         │   │
│  │  User Query → Router (classify intent) → Agent (act)    │   │
│  │                         ↓                               │   │
│  │  ├─ Carrier Vetting Agent    [DOT lookup, CSA scores]   │   │
│  │  ├─ Driver Qualification     [CDL, medical, DQ file]    │   │
│  │  ├─ CSA Scoring Agent        [BASIC analysis]           │   │
│  │  └─ Compliance Oracle        [Regulation Q&A]           │   │
│  │                         ↓                               │   │
│  │  Synthesizer → Format + cite + send response            │   │
│  └─────────────────────────────────────────────────────────┘   │
│  Purpose: Speed + composability. New agent = 1 file + 2 lines   │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  System of Continuous Improvement (The Nervous System)          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ AgentTracer (every call logged)                          │   │
│  │ ↓                                                        │   │
│  │ EvalHarness (25 ground-truth test cases)                 │   │
│  │ ├─ Carrier Vetting: 5 cases                             │   │
│  │ ├─ Driver Qualification: 5 cases                        │   │
│  │ ├─ CSA Scoring: 5 cases                                 │   │
│  │ ├─ Regulation Lookup: 6 cases                           │   │
│  │ └─ Risk Assessment: 4 cases                             │   │
│  │ ↓                                                        │   │
│  │ Scoring: keyword_recall (50%) + citation_recall (20%)   │   │
│  │         + status_accuracy (15%) + risk_accuracy (15%)   │   │
│  │ ↓                                                        │   │
│  │ Results persisted + pass rate visible in real time       │   │
│  └─────────────────────────────────────────────────────────┘   │
│  Purpose: Know what works. Iterate fast.                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components Explained

### 1. Router (Intent Classification)

**What it does:**
- Reads user query (natural language)
- Classifies into one of 5 categories in a single Claude call
- Routes to appropriate specialist

**Categories:**
```
QueryIntent enum:
  ├─ CARRIER_VETTING       → CarrierVettingAgent
  ├─ DRIVER_QUALIFICATION  → DriverQualificationAgent
  ├─ CSA_SCORING           → CSAScoringAgent
  ├─ COMPLIANCE_ORACLE     → ComplianceOracleAgent (regulation Q&A)
  └─ MULTI_DOMAIN          → ComplianceOracleAgent (complex, cross-domain)
```

**Example:**
```
User: "Run a safety check on DOT 2345678 before I tender a hazmat load."
Router classifies: CARRIER_VETTING
→ Sends to CarrierVettingAgent
```

**File:** `src/models/domain.py` (QueryIntent enum)

---

### 2. Carrier Vetting Agent

**What it does:**
- Looks up carrier by DOT number
- Retrieves CSA BASIC scores (all 7)
- Checks for alerts (4+ BASIC thresholds exceeded)
- Analyzes crash history
- Returns structured safety report

**Checks performed:**
```
✓ Operating Authority (MC/DOT registration valid?)
✓ Insurance on File (meets 49 CFR §387.9 minimums?)
✓ HazMat Flag (if hazmat shipment, is HM endorsement active?)
✓ Safety Rating (Satisfactory / Conditional / Unsatisfactory?)
✓ CSA BASIC Scores (all 7 BASICs vs thresholds)
  ├─ Vehicle Maintenance (threshold: 80.0)
  ├─ Hours of Service (threshold: 65.0)
  ├─ Unsafe Driving (threshold: 65.0)
  ├─ Crash Indicator (threshold: 65.0)
  ├─ Hazmat Compliance (threshold: 80.0)
  ├─ Driver Fitness (threshold: 80.0)
  └─ Controlled Substances (threshold: 80.0)
✓ Out-of-Service Rates (driver OOS %, vehicle OOS %)
✓ Crash History (total, fatal, injury-involved)
```

**Output:** 
```
ComplianceReport {
  status: NON_COMPLIANT | COMPLIANT | CONDITIONAL
  risk_level: CRITICAL | HIGH | MEDIUM | LOW
  reasoning: "4 BASIC alerts, Conditional safety rating, 33% vehicle OOS rate..."
  citations: ["49 CFR §385.3", "49 CFR §387.9", ...]
  latency_ms: 2345
}
```

**File:** `src/agents/carrier_vetting.py`

---

### 3. Driver Qualification Agent

**What it does:**
- Looks up driver by CDL number
- Checks Clearinghouse status (PROHIBITED, PASS, NO_RECORD)
- Verifies medical certification
- Checks DQ file completeness
- Validates endorsements for hazmat/passenger

**Checks performed:**
```
✓ CDL Valid? (class match, not expired, state check)
✓ Clearinghouse Status (49 CFR 382.705)
  ├─ PROHIBITED (disqualified)
  ├─ PASS (annual check OK)
  └─ NO_RECORD (new hire or clean)
✓ Medical Certification (FMCSA National Registry, expired?)
✓ DQ File Completeness (49 CFR 391.51)
  ├─ Application (hired date, employment history)
  ├─ MVR (motor vehicle record)
  ├─ Road Test (documented)
  ├─ Annual Review (current year)
  └─ Clearinghouse Query (annual)
✓ Endorsements (for hazmat: H, N, X required?)
✓ Restrictions (air brake, automatic transmission, etc.)
```

**Output:**
```
ComplianceReport {
  status: COMPLIANT | NON_COMPLIANT
  risk_level: LOW | HIGH | CRITICAL
  reasoning: "CDL valid, Clearinghouse PASS, medical cert current, DQ file complete..."
  citations: ["49 CFR 382.705", "49 CFR 391.51", ...]
}
```

**File:** `src/agents/driver_qual.py`

---

### 4. CSA Scoring Agent

**What it does:**
- Explains what a given CSA BASIC score means
- Provides improvement plan (what violations drive the score up?)
- Analyzes root causes and corrective actions

**CSA Background:**
```
What is CSA?
  Crash Indicator, Safety, Accountability (FMCSA program)
  Ranks carriers on 7 BASICs (Behavior Analysis and Safety Improvement Categories)
  
How do scores work?
  • Percentile-based (0-100)
  • Time-weighted (recent violations count more)
  • Intervention threshold varies by BASIC (typically 65-80)
  • Below threshold = OK, Above = alert
  
Who can intervene?
  • FMCSA can open investigation (49 CFR §385 Subpart A)
  • Broker/shipper can decline carrier (negligent selection defense)
```

**Example improvement plan for HOS score 82.1:**
```
HOS BASIC (Hours of Service) = 82.1 — ALERT (threshold 65.0)

What violations drive this?
  ├─ 11-hour driving limit (49 CFR 395.8(a)) — 3 violations
  ├─ 14-hour window (49 CFR 395.8(a)) — 2 violations
  ├─ 60/70-hour rule (49 CFR 395.8(b)) — 1 violation
  └─ ELD violations (49 CFR 395.22) — 4 violations

How to fix?
  1. Audit ELD configuration (off by 15 min each day = 375 min/month)
  2. Adjust dispatcher scheduling (respect 14-hour window)
  3. Train on 34-hour restart requirements (49 CFR 395.8(d))
  4. Ensure proper sleeper berth usage (49 CFR 395.8(c))
```

**File:** `src/agents/csa_scoring.py`

---

### 5. Compliance Oracle Agent

**What it does:**
- Answers regulatory questions (Q&A over regulations)
- Uses Claude Opus (more powerful, better at reasoning)
- Retrieves relevant CFR sections before answering
- Used for multi-domain questions

**Examples:**
```
Q: "How does the 34-hour restart work? What are the 1am-5am requirements?"
→ Oracle retrieves 49 CFR 395.8(d) + interprets
→ Answer: "A 34-hour restart means no driving for 34 consecutive hours 
          after being on duty. If you take this break between 1am-5am 
          for 2 nights, you get additional benefit (49 CFR 395.8(d)(1)(ii))..."

Q: "What are the insurance minimums for a 5-truck hazmat carrier?"
→ Oracle retrieves 49 CFR §387 (Insurance Requirements)
→ Answer: "$5 million for hazmat general cargo (49 CFR §387.7(d)(1))..."
```

**File:** `src/agents/compliance_oracle.py`

---

### 6. Synthesizer

**What it does:**
- Takes agent response
- Ensures all claims are cited
- Adds urgency signal (if risk is high, flag it clearly)
- Formats for readability

**Example:**
```
Raw agent output: "Score 91.3 means alert."
Synthesizer output: 
  "Vehicle Maintenance score of 91.3 is above the 80.0 intervention 
   threshold (49 CFR §385). This indicates systemic brake/equipment issues."
```

**File:** `src/graph/orchestrator.py` (_synthesizer_node)

---

## Data Flow

### Full Request → Response Lifecycle

```
1. USER SUBMITS QUERY
   └─ Example: "Run a safety check on DOT 2345678"

2. ROUTER CLASSIFIES
   └─ Intent: CARRIER_VETTING
   └─ Model: claude-sonnet-4-6 (fast, low-cost)

3. CARRIER VETTING AGENT EXECUTES
   ├─ Retrieve carrier data (mock: src/data/mock/carriers.json)
   ├─ Get CSA scores
   ├─ Get crash history
   ├─ Build regulatory context (retrieve from ChromaDB)
   └─ Model: claude-sonnet-4-6 (tool-use loop)

4. TOOL DISPATCH
   Agent calls tools:
   ├─ lookup_carrier(dot=2345678) → returns mock data
   ├─ get_csa_scores(dot=2345678) → returns BASIC scores
   ├─ get_crash_history(dot=2345678) → returns crashes
   └─ [Agent loops until it has all needed info or calls stop_tool]

5. REASONING
   ├─ Claude reads all tool outputs
   ├─ Claude reads regulatory context (from KB)
   ├─ Claude reasons: "This carrier is above 4 thresholds + 33% OOS = HIGH RISK"
   └─ Claude structures response as ComplianceReport

6. SYNTHESIZER FORMATS
   ├─ Checks all claims have citations
   ├─ Adds [49 CFR §385.3] references
   ├─ Formats for display
   └─ Adds timestamp + latency

7. TRACE RECORDED
   ├─ Trace ID (UUID)
   ├─ Query + intent
   ├─ Tokens used (prompt + completion)
   ├─ Model used
   ├─ Latency (ms)
   ├─ All tool calls
   ├─ Final response
   └─ Persisted to: evals/results/traces_YYYYMMDD.jsonl

8. RESPONSE RETURNED
   └─ Displayed in CLI / returned via API

9. OPTIONAL: EVAL
   ├─ If eval mode enabled:
   │  ├─ Compare response against ground truth
   │  ├─ Score: keyword_recall + citation_recall + accuracy
   │  └─ Aggregate to pass/fail
   └─ If interactive mode: Wait for next query
```

---

## The Four Agents

### Agent Capability Matrix

```
┌──────────────────┬────────────┬──────────────┬──────────────┬──────────────┐
│ Agent            │ Input      │ Output       │ Model        │ Latency      │
├──────────────────┼────────────┼──────────────┼──────────────┼──────────────┤
│ Carrier Vetting  │ DOT number │ Safety score │ sonnet-4-6   │ 2-5s         │
│                  │            │ + report     │ (tool-use)   │              │
├──────────────────┼────────────┼──────────────┼──────────────┼──────────────┤
│ Driver Qual      │ CDL number │ Compliance   │ sonnet-4-6   │ 1-3s         │
│                  │            │ status       │ (tool-use)   │              │
├──────────────────┼────────────┼──────────────┼──────────────┼──────────────┤
│ CSA Scoring      │ DOT + BASIC│ Improvement  │ sonnet-4-6   │ 2-4s         │
│                  │ score      │ plan + root  │ (tool-use)   │              │
│                  │            │ cause        │              │              │
├──────────────────┼────────────┼──────────────┼──────────────┼──────────────┤
│ Compliance       │ Free-form  │ Regulation   │ opus-4-7     │ 5-15s        │
│ Oracle           │ question   │ Q&A + cite   │ (RAG)        │              │
└──────────────────┴────────────┴──────────────┴──────────────┴──────────────┘

Model choices:
  sonnet-4-6: Fast ($0.003/$0.015 per 1K tokens), good for structured tasks
  opus-4-7: Expensive ($0.015/$0.075 per 1K), best for reasoning + RAG
```

### Tool-Use Loop Example (Carrier Vetting)

```
Iteration 1:
  Agent thinks: "I need to look up this carrier"
  → Calls: lookup_carrier(dot=2345678)
  ← Returns: {"dot": 2345678, "name": "Red Line Transport", ...}

Iteration 2:
  Agent thinks: "I need CSA scores for safety assessment"
  → Calls: get_csa_scores(dot=2345678)
  ← Returns: {"vehicle_maintenance": 91.3, "hos": 82.1, ...}

Iteration 3:
  Agent thinks: "I need crash history to assess risk"
  → Calls: get_crash_history(dot=2345678)
  ← Returns: [{"type": "fatal", "date": "2024-01-15"}, ...]

Iteration 4:
  Agent thinks: "I have all info. I can now reason and respond"
  → Calls: stop_tool()
  ← Agent outputs final ComplianceReport
```

---

## Knowledge Base

### ChromaDB Vector Store

**What's stored:**
```
30 regulatory chunks:
  ├─ 49 CFR Part 395 (HOS) — 8 chunks
  ├─ 49 CFR Part 391 (Driver Qual) — 7 chunks
  ├─ CSA BASIC scoring — 5 chunks
  ├─ 49 CFR Part 387 (Insurance) — 5 chunks
  └─ Hazmat/Endorsement rules — 5 chunks
```

**How it's used:**
```
When agent needs context:
  1. Build search query (related to current problem)
  2. Search ChromaDB (cosine similarity on embeddings)
  3. Retrieve top-5 chunks with citations
  4. Include in Claude prompt as context

Example:
  Query: "vehicle maintenance violations"
  → Search returns:
     [1] "49 CFR §396: Every commercial motor vehicle shall be..."
     [2] "Brake violations are most common (45% of OOS events)..."
     [3] "BASIC threshold for Vehicle Maintenance is 80.0 percentile..."
```

**Ingestion:**
```
data/regulations/
├── fmcsa_hos.md          (loaded)
├── fmcsa_driver_qual.md  (loaded)
├── csa_scoring.md        (loaded)
├── operating_authority.md (loaded)
└── hazmat_compliance.md  (loaded)

On startup:
  RegulationLoader.load_all() 
  → Splits into chunks (~500 chars each)
  → Assigns ID, title, citation, category
  → Ingested into ChromaDB
  → Embeddings computed (SentenceTransformer: all-MiniLM-L6-v2)
```

**File:** `src/knowledge/vectorstore.py`

---

## Evaluation System

### 25 Ground-Truth Test Cases

**Structure:**
```
EvalCase {
  id: "CV-001"  # Category-Number
  category: QueryIntent (CARRIER_VETTING, etc.)
  query: "Run a safety check on DOT 2345678..."
  expected_status: ComplianceStatus.NON_COMPLIANT
  expected_risk: RiskLevel.CRITICAL
  expected_keywords: ["alert", "threshold", "conditional", ...]
  expected_regulation_refs: ["49 CFR §385", "49 CFR §387", ...]
  description: "Dangerous carrier scenario"
}
```

**Scoring Formula:**
```
score = 0.5 × keyword_recall 
      + 0.2 × citation_recall 
      + 0.15 × status_accuracy 
      + 0.15 × risk_accuracy

Where:
  keyword_recall = (keywords_found / expected_keywords) × 100
  citation_recall = (citations_found / expected_refs) × 100
  status_accuracy = 1.0 if response.status == expected.status else 0.0
  risk_accuracy = 1.0 if response.risk == expected.risk else 0.0

Pass threshold: score ≥ 0.60 (60%)
```

**Example Case: Carrier Vetting**
```
CV-001: "Run a safety check on DOT 2345678 before tendering hazmat"
Expected: 
  ├─ Status: NON_COMPLIANT
  ├─ Risk: CRITICAL
  ├─ Keywords: ["alert", "conditional", "maintenance", "threshold", "hazmat"]
  └─ Citations: ["49 CFR §385.3", "49 CFR §387.9", "49 CFR §396"]

If response gets:
  ├─ Status: NON_COMPLIANT ✓ (15% accuracy)
  ├─ Risk: CRITICAL ✓ (15% accuracy)
  ├─ Keywords: 5/5 found ✓ (50% recall)
  └─ Citations: 2/3 found ✗ (67% recall × 20% weight)
  → Score = 50% + 13.4% + 15% + 15% = 93.4% → PASS
```

**Run Eval:**
```bash
python demo/cli.py eval
# Output: 22 passed, 3 failed (88% pass rate)

python demo/cli.py eval --category driver_qualification
# Output: 5 passed, 0 failed (100% pass rate)
```

**Files:**
- `src/eval/test_cases.py` — 25 cases defined
- `src/eval/harness.py` — Scoring + persistence
- `evals/results/eval_*.json` — Results stored here

---

## File Structure & Key Files

```
freightmind-ai/
│
├── src/                           ← Main codebase
│   ├── models/
│   │   └── domain.py              ← Pydantic models + enums
│   │                              ├─ QueryIntent
│   │                              ├─ ComplianceStatus
│   │                              ├─ RiskLevel
│   │                              ├─ ComplianceReport
│   │                              └─ AgentTrace
│   │
│   ├── knowledge/
│   │   ├── regulations.py         ← RegulationLoader + chunking
│   │   └── vectorstore.py         ← ChromaDB ingest/search
│   │
│   ├── agents/
│   │   ├── base.py                ← BaseComplianceAgent + tool-loop
│   │   ├── carrier_vetting.py     ← CarrierVettingAgent
│   │   ├── driver_qual.py         ← DriverQualificationAgent
│   │   ├── csa_scoring.py         ← CSAScoringAgent
│   │   └── compliance_oracle.py   ← ComplianceOracleAgent
│   │
│   ├── graph/
│   │   └── orchestrator.py        ← LangGraph state machine
│   │                              ├─ Router node
│   │                              ├─ 4 agent nodes
│   │                              ├─ Synthesizer node
│   │                              └─ Conditional routing
│   │
│   ├── eval/
│   │   ├── test_cases.py          ← 25 EvalCase definitions
│   │   └── harness.py             ← Scoring + persistence
│   │
│   ├── observability/
│   │   └── tracer.py              ← AgentTracer (JSONL output)
│   │
│   └── api/
│       └── main.py                ← FastAPI endpoints (6 routes)
│
├── demo/
│   └── cli.py                     ← Rich terminal CLI
│                                  ├─ interactive mode
│                                  ├─ demo mode (5 queries)
│                                  ├─ query mode (single)
│                                  └─ eval mode (run harness)
│
├── data/
│   ├── regulations/               ← Knowledge base source docs
│   │   ├── fmcsa_hos.md
│   │   ├── fmcsa_driver_qual.md
│   │   ├── csa_scoring.md
│   │   ├── operating_authority.md
│   │   └── hazmat_compliance.md
│   ├── mock/
│   │   ├── carriers.json          ← Mock carrier data (30 carriers)
│   │   └── drivers.json           ← Mock driver data (20 drivers)
│   └── chroma/                    ← Persisted embeddings (created on first run)
│
├── evals/
│   └── results/                   ← Eval run outputs (JSON)
│
├── .env                           ← Local config (API keys, model names)
├── .env.example                   ← Template
├── pyproject.toml                 ← Dependencies + project config
├── README.md                       ← High-level overview
└── PROJECT_GUIDE.md               ← This file
```

---

## How to Extend

### Add a New Agent (Example: Insurance Underwriting)

**Step 1: Create agent file**
```python
# src/agents/insurance_agent.py

from src.agents.base import BaseComplianceAgent

class InsuranceUnderwritingAgent(BaseComplianceAgent):
    name = "insurance_underwriting"
    
    @property
    def system_prompt(self) -> str:
        return "You are an expert insurance underwriter for motor carriers..."
    
    @property
    def tools(self) -> list[dict]:
        return [
            {"name": "lookup_insurance_policy", ...},
            {"name": "get_claims_history", ...},
        ]
    
    def _dispatch_tool(self, tool_name: str, tool_input: dict):
        if tool_name == "lookup_insurance_policy":
            # Your tool logic
            pass
```

**Step 2: Add to orchestrator**
```python
# src/graph/orchestrator.py

class FreightMindOrchestrator:
    def __init__(self):
        ...
        self._insurance_agent = InsuranceUnderwritingAgent()  # Add this
        self._graph = self._build_graph()
    
    def _build_graph(self) -> Any:
        builder = StateGraph(FreightState)
        ...
        builder.add_node("insurance_underwriting", self._insurance_node)  # Add node
        builder.add_conditional_edges(
            "router",
            self._route_to_agent,
            {
                ...
                "insurance_underwriting": "insurance_underwriting",  # Add route
            },
        )
        ...
```

**Step 3: Add intent to QueryIntent enum**
```python
# src/models/domain.py

class QueryIntent(str, Enum):
    ...
    INSURANCE_UNDERWRITING = "insurance_underwriting"
```

**Step 4: (Optional) Add test cases**
```python
# src/eval/test_cases.py

TEST_CASES = [
    ...
    EvalCase(
        id="INS-001",
        category=QueryIntent.INSURANCE_UNDERWRITING,
        query="What's the insurance profile for carrier DOT 1234567?",
        ...
    ),
]
```

That's it! New agent is now routable.

---

### Add a New Evaluation Case

```python
# src/eval/test_cases.py

EvalCase(
    id="CV-006",  # Next carrier vetting case
    category=QueryIntent.CARRIER_VETTING,
    query="Is SafeHaul Inc (DOT 5555555) safe for food freight?",
    expected_status=ComplianceStatus.COMPLIANT,
    expected_risk=RiskLevel.LOW,
    expected_keywords=["satisfactory", "compliant", "low risk", "clean"],
    expected_regulation_refs=["49 CFR §385.3", "49 CFR §387.9"],
    description="Good carrier scenario - control/baseline"
),
```

Then run:
```bash
python demo/cli.py eval
# New case is automatically scored
```

---

### Add Knowledge to Vector Store

**Option 1: Add markdown file**
```markdown
# data/regulations/my_topic.md

## Title
This is regulatory text...

## 49 CFR §123.45
The regulation states: ...

## Key Points
- Point 1
- Point 2
```

RegulationLoader will automatically pick it up on next `kb.ingest()`.

**Option 2: Manually ingest**
```python
from src.knowledge.vectorstore import FreightKnowledgeBase

kb = FreightKnowledgeBase()
kb.ingest(force=True)  # force=True re-ingests all
```

---

## Quick Reference: Commands

```bash
# Setup
pip install -e ".[dev]"
cp .env.example .env
# Add ANTHROPIC_API_KEY to .env

# Run
python demo/cli.py interactive         # Interactive Q&A loop
python demo/cli.py demo                # Run 5 demo queries
python demo/cli.py eval                # Run all 25 test cases
python demo/cli.py query "Your query"  # Single query
python -m pytest evals -v              # Run pytest suite
uvicorn src.api.main:app --reload      # Start API server (port 8000)

# Check
python -c "from src.knowledge.vectorstore import FreightKnowledgeBase; kb=FreightKnowledgeBase(); print(f'KB has {kb.count} chunks')"
```

---

## Key Concepts

### ComplianceStatus Enum
```
COMPLIANT     → No violations, safe to use
NON_COMPLIANT → Violations found, do not use
CONDITIONAL   → Partial violations, use with caution (requires review)
```

### RiskLevel Enum
```
LOW      → Green light
MEDIUM   → Yellow flag (review before use)
HIGH     → Orange alert (use with extreme caution)
CRITICAL → Red stop (do not use)
```

### QueryIntent Enum
```
CARRIER_VETTING      → Is this carrier safe?
DRIVER_QUALIFICATION → Can this driver work?
CSA_SCORING          → What's driving this score?
COMPLIANCE_ORACLE    → What does the regulation say?
MULTI_DOMAIN         → Complex cross-domain question
```

### AgentTrace (Audit Trail)
```
Every agent call creates an AgentTrace:
  ├─ trace_id (UUID, globally unique)
  ├─ agent_name
  ├─ query (user input)
  ├─ model_used
  ├─ started_at / completed_at
  ├─ latency_ms
  ├─ tokens_in / tokens_out
  ├─ tool_calls (list of all tools invoked)
  └─ response (final answer)

Persisted to: evals/results/traces_YYYYMMDD.jsonl
Searchable for audit + debugging
```

---

## Design Principles

| Principle | How It's Applied |
|-----------|------------------|
| **Grounded** | Every regulation claim is retrieved from KB before responding |
| **Composable** | New agent = 1 file + 2 lines in orchestrator |
| **Observable** | Every call traced, latency recorded, results evaluated |
| **Direct** | Clear recommendation (PASS/FAIL/CONDITIONAL), not a hedge |
| **Fast** | Router runs in 1 Claude call, agents in parallel |

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'src'"
```bash
# Make sure you're using the venv Python:
.venv/bin/python demo/cli.py query "..."

# Or activate the venv:
source .venv/bin/activate
python demo/cli.py query "..."
```

### "ANTHROPIC_API_KEY not set"
```bash
# Check your .env file:
cat .env
# Should show: ANTHROPIC_API_KEY=sk-ant-...

# If missing, add it:
echo "ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE" >> .env
```

### Low eval pass rate
```bash
# Run eval with verbose output:
python demo/cli.py eval
# Check: evals/results/eval_*.json

# Debug a single case:
python -c "
from src.eval.test_cases import TEST_CASES
case = TEST_CASES[0]
print(f'Case: {case.id}')
print(f'Query: {case.query}')
print(f'Expected: {case.expected_keywords}')
"
```

---

## Next Steps

1. **Run interactive demo:** `python demo/cli.py interactive`
2. **Review a carrier:** `python demo/cli.py query "Check DOT 2345678"`
3. **Check eval results:** `python demo/cli.py eval`
4. **Add a new agent:** Follow [Add a New Agent](#add-a-new-agent-example-insurance-underwriting)
5. **Deploy API:** `uvicorn src.api.main:app --reload`

