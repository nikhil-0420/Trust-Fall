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

---

## Post-Submission Cleanup Checklist (Phase N8)

After hackathon submission and judging:
1. **Delete Agent37 Sandbox:**
   - If a live sandbox instance was created, terminate it via curl or dashboard:
     ```bash
     curl -X DELETE "https://api.agent37.com/v1/instances/<SANDBOX_ID>" -H "Authorization: Bearer <AGENT37_API_KEY>"
     ```
2. **Stop BAND Agents & Rooms:**
   - Terminate active background agent runners and remove test rooms at `https://app.band.ai`.
3. **Key Rotation Check:**
   - If the repository was ever made public before submission or secrets were accidentally shared, rotate `GEMINI_API_KEY`, `AGENT37_API_KEY`, `LYZR_API_KEY`, and `BAND` API keys immediately.
4. **Repository Metadata:**
   - Set GitHub repository description: *"Trust Fall — Red-vs-Blue Security Arena for Multi-Agent Systems"*.
   - Set repository tags/topics: `multi-agent-systems`, `ai-security`, `red-teaming`, `prompt-injection`, `band-ai`, `agent37`, `lyzr`.



- Created Agent37 instance. Remember to delete it after submission: DELETE https://api.agent37.com/v1/instances/$SANDBOX_ID
