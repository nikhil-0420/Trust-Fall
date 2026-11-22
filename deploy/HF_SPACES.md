# Deploying Trust Fall to Hugging Face Spaces (Docker)

Trust Fall can be hosted on Hugging Face Spaces as a Docker Space on the free tier.

---

## 1. Space Creation

1. Navigate to [huggingface.co/new-space](https://huggingface.co/new-space).
2. Set **Space Name** to `trustfall-api`.
3. Select **Space SDK:** `Docker` -> `Blank`.
4. Choose **Public** visibility.

---

## 2. Port Configuration

Hugging Face Spaces expects web containers to listen on port **7860**.
In the Space settings or via environment variable, set:
```
PORT=7860
```
Our `deploy/Dockerfile` automatically respects `${PORT:-8000}` and will bind `uvicorn` to port 7860 when `PORT=7860` is set.

---

## 3. Secret Configuration

Never commit secrets to git. In your Space:
1. Go to **Settings** -> **Variables and secrets**.
2. Under **Secrets**, add:
   - `INTERNAL_TOKEN`: Shared secret for Dispatcher authentication.
   - `GEMINI_API_KEY`: Google AI Studio API key.
   - `LYZR_API_KEY`: Lyzr AI platform detector API key.
   - `AGENT37_API_KEY`: Agent37 sandbox API key.
   - `BAND_AGENT_A_KEY`, `BAND_AGENT_B_KEY`: BAND credentials.
3. Under **Variables**, add:
   - `ALLOWED_ORIGINS`: Your Vercel frontend URL (e.g. `https://trustfall-web.vercel.app`).
   - `USE_MOCKS`: `1` by default (switch to `0` only after testing).
   - `LIVE_APPROVED`: `0` by default.

---

## 4. Free-Tier Sleep Behavior & Caveats

- **Inactivity Sleep:** Free Spaces sleep after 48 hours of inactivity.
- **Cold Start:** An incoming request after sleep wakes the container in approximately 30 to 60 seconds.
- **Judging Day Fallback:** During live hackathon judging, use the Cloudflare Tunnel fallback (`python scripts/tunnel.py`) on a local machine to guarantee zero cold start and instant latency.
