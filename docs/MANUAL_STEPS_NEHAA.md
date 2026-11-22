# Manual Steps (Nehaa)

Steps that require human intervention in a browser, external dashboard, or cloud console.

---

### 1. Quota & Limits Verification
1. **Lyzr Dashboard:**
   - Log into [Lyzr Dashboard](https://dashboard.lyzr.ai).
   - Note the credit count.
   - Run 5 detector test calls using `scripts/measure_limits.py` (when approved).
   - Check if credit balance decreases, and log the finding in `docs/LIMITS.md`.
2. **Google AI Studio Quota:**
   - Open Google AI Studio -> Settings -> Plan & Billing / Quotas.
   - Check the tier limits (RPM, RPD) for `gemini-2.5-flash`.
   - Record in `docs/LIMITS.md` and set `LLM_DAILY_CAP` (default 200) and `LYZR_DAILY_CAP` (default 15) accordingly.

---

### 2. External Deployment Setup
Choose one of the hosting targets documented in `docs/DEPLOY.md`:

1. **Option A: Render.com (Recommended for judging)**
   - Connect GitHub repository `TrustFall`.
   - Create a Web Service with Docker runtime (or use `deploy/render.yaml` Blueprint).
   - Set Environment Variables in Render Dashboard:
     - `USE_MOCKS=1` (or `0` once live approved)
     - `INTERNAL_TOKEN` (generate using `python -c "import secrets; print(secrets.token_hex(32))"`)
     - `ALLOWED_ORIGINS` (set to Nikhil's Vercel deployment URL, e.g. `https://trustfall.vercel.app`)
     - `GEMINI_API_KEY`, `LYZR_API_KEY`, `AGENT37_API_KEY`, `BAND_*` keys
   - Copy the allocated Render URL (e.g. `https://trustfall-api.onrender.com`) and provide to Nikhil as `VITE_API_URL`.

2. **Option B: Hugging Face Spaces (Fallback)**
   - Create a new Space at huggingface.co/spaces with Docker SDK.
   - Port must be set to `7860` (see `deploy/HF_SPACES.md`).
   - Add environment variables under Space Settings -> Variables and Secrets.

3. **Option C: Cloudflare Tunnel (Judging / Live Demo Fallback)**
   - Run `python scripts/tunnel.py` on local machine with the app running.
   - Share the generated `trycloudflare.com` URL with the frontend.

---

### 3. Dispatcher Gate Wiring
- Ensure the Worker or Dispatcher running inside or alongside the sandbox has `GATE_URL` pointing to the public API endpoint (e.g. `https://trustfall-api.onrender.com/internal/screen`).
- Verify `X-Internal-Token` header matches `INTERNAL_TOKEN`.

---

### 4. Sandbox Cleanup & Token Rotation
1. **Agent37 Sandbox Teardown:**
   - When the hackathon judging concludes, terminate any active sandboxes in the Agent37 dashboard or via CLI.
2. **Token Rotation:**
   - If `INTERNAL_TOKEN` is compromised or rotated, generate a new token and update both backend (`INTERNAL_TOKEN`) and Dispatcher (`GATE_TOKEN`).
