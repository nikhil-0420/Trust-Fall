# Manual Steps (Nikhil)

Steps that require human intervention in a browser or external dashboard.

---

## BAND Agent Registration Steps (Phase N3)

If BAND keys are missing or when registering live agents:
1. Navigate to `https://app.band.ai` in your browser.
2. Under Agent Management, choose **Connect Remote Agent**.
3. Register three additional agents:
   - **Red Agent**: Copy ID to `BAND_AGENT_RED_ID` and Key to `BAND_AGENT_RED_KEY` in `.env`.
   - **Blue Agent**: Copy ID to `BAND_AGENT_BLUE_ID` and Key to `BAND_AGENT_BLUE_KEY` in `.env`.
   - **Analyst Agent**: Copy ID to `BAND_AGENT_ANALYST_ID` and Key to `BAND_AGENT_ANALYST_KEY` in `.env`.
4. Ensure **Personal Registry Access** remains checked for all agents.
5. Create a shared room named **"Trust Fall Arena"** and invite all participants (Agent A / Dispatcher, Agent B / Worker, Red, Blue, Analyst).
6. Copy the resulting Room ID to `BAND_ROOM_ID` in `.env`.

