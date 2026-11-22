# Submission Notes (Nehaa)

This document tracks the status of all backend submission items from `docs/BACKEND_PLAN.md` (Section 13) and compiles all open manual human steps.

---

## 1. Backend Submission Checklist (`docs/BACKEND_PLAN.md` Section 13)

| Item | Status | Notes |
|---|---|---|
| **Public repo `Trust-Fall` under `nikhil-0420` with README** | **DONE** | Complete README with architecture diagram, sponsor details, setup instructions, API reference, and safety notices. |
| **`.env.example` present, no secrets in history** | **DONE** | `.env.example` verified; `scripts/secret_scan.py --history` passes cleanly across the entire commit tree. |
| **`results.json`, `events/*.jsonl`, reports committed** | **DONE (Mock) / NEEDS HUMAN (Live)** | Complete mock dataset and reports generated and committed in `data/mock/` and `data/reports/`. Live data will replace them once H8 is run. |
| **Hosted API URL live and tested from a phone** | **NEEDS HUMAN** | Deployment configs (`deploy/Dockerfile`, `deploy/render.yaml`, `deploy/HF_SPACES.md`, `scripts/tunnel.py`) are ready; requires human cloud account deployment on Render or Cloudflare Tunnel during judging. |
| **Real numbers copied into the submission form** | **NEEDS HUMAN** | Dependent on the live H8 execution on the machine containing the live API keys. |
| **Sandbox and extra agents deleted after submission** | **NEEDS HUMAN** | Teardown procedures documented in both manual steps files to avoid ongoing resource charges. |

---

## 2. Open Human Steps

### From `docs/MANUAL_STEPS_NEHAA.md`:
1. **Lyzr Credit Verification:**
   - Log into [Lyzr Dashboard](https://dashboard.lyzr.ai).
   - Record credit balance, test 5 detector calls via `scripts/measure_limits.py`, and fill in `docs/LIMITS.md`.
2. **Google AI Studio Quota Check:**
   - Check Google AI Studio Settings -> Quotas for `gemini-2.5-flash` RPM and RPD limits.
   - Record findings in `docs/LIMITS.md` and adjust `LLM_DAILY_CAP`.
3. **API Cloud Deployment:**
   - Deploy Docker container to Render (`deploy/render.yaml`) or launch `python scripts/tunnel.py`.
   - Set environment variables (`INTERNAL_TOKEN`, `ALLOWED_ORIGINS`, `GEMINI_API_KEY`, `LYZR_API_KEY`).
   - Share URL with Nikhil (`VITE_API_URL`).
4. **Dispatcher Gate Target:**
   - Confirm Worker/Dispatcher `GATE_URL` points to public `/internal/screen` endpoint.

### From `docs/MANUAL_STEPS_NIKHIL.md`:
1. **BAND Agent Registration:**
   - Register Red, Blue, and Analyst agents in BAND dashboard (`https://app.band.ai`).
   - Configure shared room "Trust Fall Arena".
2. **Post-Submission Resource Cleanup:**
   - Delete Agent37 sandbox instance (`curl -X DELETE ...`).
   - Terminate active BAND background agent runners and remove test rooms.
   - Verify token rotations and set GitHub repository description and topics.
