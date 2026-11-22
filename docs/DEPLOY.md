# Trust Fall — Deployment Runbook

Comprehensive deployment instructions, hosting alternatives, environment configuration, and operational checklist.

---

## 1. Hosting Alternatives

You can deploy the Trust Fall backend to any of the following targets:

| Host | Best For | Cold Start | Instructions |
|---|---|---|---|
| **Render** | Production web service | ~50s on free tier | Push to GitHub, link repo in Render Dashboard using `deploy/render.yaml` |
| **Hugging Face Spaces** | Free Docker hosting | ~40s on free tier | Create Docker Space on HF, set `PORT=7860` (see `deploy/HF_SPACES.md`) |
| **Cloudflare Tunnel** | **Judging Day Fallback (Recommended)** | **0s (instant)** | Run locally via `python scripts/tunnel.py` |

---

## 2. Required Environment Variables

Configure these variables in your host's dashboard (never commit them to git):

| Variable | Description | Example / Default |
|---|---|---|
| `ALLOWED_ORIGINS` | Vercel frontend URL(s), comma-separated | `https://trustfall-web.vercel.app` |
| `INTERNAL_TOKEN` | Shared secret for internal screening calls | 32-character hex secret |
| `GEMINI_API_KEY` | Google AI Studio key for Gemini completions | `AIza...` |
| `LYZR_API_KEY` | Lyzr Prompt Injection detector key | `lyzr-...` |
| `AGENT37_API_KEY` | Agent37 sandbox access key | `sk-agt37-...` |
| `SANDBOX_ID` | Active Agent37 sandbox identifier | `sbx-123456` |
| `BAND_AGENT_A_ID` | BAND Dispatcher agent ID | `agt_disp_...` |
| `BAND_AGENT_A_KEY` | BAND Dispatcher secret | `...` |
| `BAND_AGENT_B_ID` | BAND Worker agent ID | `agt_work_...` |
| `BAND_AGENT_B_KEY` | BAND Worker secret | `...` |
| `USE_MOCKS` | Mock mode toggle (`1` = mock, `0` = live) | `1` (default for safety) |
| `LIVE_APPROVED` | Explicit approval flag for live API spending | `0` (default) |
| `TRANSPORT` | Transport implementation (`mock` / `loopback` / `band`) | `mock` |
| `LLM_DAILY_CAP` | Daily budget limit for LLM calls | `200` |
| `LYZR_DAILY_CAP` | Daily budget limit for Lyzr detector calls | `15` |

---

## 3. Worker Gateway Configuration (`GATE_URL`)

The Worker agent running inside the Agent37 sandbox requires network access to the API's `/internal/screen` endpoint.
In the sandbox `.env`:
```bash
GATE_URL=https://<your-public-api-domain>
# Or when using tunnel:
GATE_URL=https://<random-id>.trycloudflare.com
INTERNAL_TOKEN=<same_secret_as_api>
```

---

## 4. Post-Deployment Verification Checklist

After deploying the container, perform these 5 checks:

1. **Liveness Probe:**
   ```bash
   curl -I https://<your-api-url>/api/health
   # Expected: HTTP 200 {"status": "ok"}
   ```
2. **Status Check:**
   ```bash
   curl https://<your-api-url>/api/status
   # Expected: HTTP 200 {"mode": "replay"|"live", "worker": "up", ...}
   ```
3. **CORS Validation:**
   ```bash
   curl -H "Origin: https://trustfall-web.vercel.app" \
        -I https://<your-api-url>/api/health
   # Verify Access-Control-Allow-Origin header is present
   ```
4. **Phone / External Network Check:**
   Open `https://<your-api-url>/api/health` on your phone browser (off Wi-Fi) to confirm external DNS resolution and firewall allowance.
5. **Frontend Link:**
   Set `VITE_API_URL=https://<your-api-url>` in Vercel project settings and trigger a redeploy.

---

## 5. Cold Starts & Judging Fallback

- Free-tier cloud containers (Render / HF Spaces) go to sleep after periods of inactivity.
- **Judging Day Rule:** For live hackathon evaluation, run:
  ```bash
  python scripts/tunnel.py
  ```
  Copy the generated `https://xxxx.trycloudflare.com` URL into `VITE_API_URL` on Vercel and `GATE_URL` in the sandbox. This eliminates cold start latency entirely.

---

## 6. Token Rotation (`INTERNAL_TOKEN`)

If `INTERNAL_TOKEN` is compromised or needs rotation:
1. Generate a new cryptographically secure token:
   ```bash
   python -c "import secrets; print(secrets.token_hex(24))"
   ```
2. Update `INTERNAL_TOKEN` in the hosted API environment settings.
3. Update `INTERNAL_TOKEN` in the sandbox environment (`GATE_URL` client).
4. Restart both services.
