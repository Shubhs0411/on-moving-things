#!/usr/bin/env bash
set -euo pipefail

# RigCompass project demo script
# Purpose: show LangGraph visibility, HITL interrupt/resume, multimodal ingest, and eval signal.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Create it and install deps first."
  exit 1
fi

source .venv/bin/activate

echo "[1/7] Running architecture view"
python demo/cli.py architecture --mermaid | head -n 20

echo
echo "[2/7] Starting API server"
uvicorn src.api.main:app --host 127.0.0.1 --port 8000 >/tmp/rigcompass_demo_uvicorn.log 2>&1 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT
sleep 2

echo
echo "[3/7] Fetch LangGraph architecture from API"
curl -s http://127.0.0.1:8000/v1/graph/architecture | python -m json.tool

echo
echo "[4/7] Start HITL query (expected: waiting_for_human)"
HITL_START_JSON="$(curl -s -X POST http://127.0.0.1:8000/v1/compliance/query/hitl \
  -H "Content-Type: application/json" \
  -d '{"query":"Should we approve DOT 2345678 for a high-value hazmat load today?"}')"
echo "$HITL_START_JSON" | python -m json.tool
THREAD_ID="$(HITL_START_JSON="$HITL_START_JSON" python - <<'PY'
import json,os
payload=json.loads(os.environ['HITL_START_JSON'])
print(payload.get('thread_id',''))
PY
)"

if [[ -z "$THREAD_ID" ]]; then
  echo "No thread_id returned from HITL start."
  exit 1
fi

echo
echo "[5/7] Resume HITL with explicit approval"
curl -s -X POST "http://127.0.0.1:8000/v1/compliance/query/hitl/${THREAD_ID}/resume" \
  -H "Content-Type: application/json" \
  -d '{"approved": true, "reviewer_note": "Approved for operational demo"}' | python -m json.tool

echo
echo "[5b/7] DQF audit MVP"
curl -s -X POST "http://127.0.0.1:8000/v1/dqf/audit" \
  -H "Content-Type: application/json" \
  -d '{
    "packet": {
      "employment_application": true,
      "mvr_initial": false,
      "mvr_annual_review_date": "2024-01-10",
      "medical_certificate_expiration": "2025-01-05",
      "road_test_or_cdl_copy": true,
      "clearinghouse_preemployment_query": false
    }
  }' | python -m json.tool

echo
echo "[6/7] Queue async ingestion job (text modality)"
JOB_JSON="$(curl -s -X POST "http://127.0.0.1:8000/v1/ingest/jobs?modality=text&source=49%20CFR%20395.3(a)(1)%20limits%20driving%20time&category=REGULATION")"
echo "$JOB_JSON" | python -m json.tool
JOB_ID="$(JOB_JSON="$JOB_JSON" python - <<'PY'
import json,os
payload=json.loads(os.environ['JOB_JSON'])
print(payload.get('job_id',''))
PY
)"

if [[ -n "$JOB_ID" ]]; then
  echo "Polling job status once:"
  curl -s "http://127.0.0.1:8000/v1/ingest/jobs/${JOB_ID}" | python -m json.tool
fi

echo
echo "[7/7] Quick quality signal"
python demo/cli.py eval --n 5 || true

echo
echo "Demo complete."
