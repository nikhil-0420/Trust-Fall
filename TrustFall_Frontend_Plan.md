# Trust Fall — Frontend Build Plan

**Owner:** Nikhil
**Deadline:** Tue 24 Nov 2026, 10:00 PM IST. Target: live on Vercel and tested by Tue 12:00.
**Companion doc:** `TrustFall_Backend_Plan.md` (section 6 holds the contracts; they are mirrored in section 3 below. If you change one, change both.)

---

## 1. Goals and principles

Trust Fall's site is both the **product page** and the **proof**. Judges should understand the idea in 10 seconds, watch it work in 60, and try to break it themselves in 2 minutes.

1. **Data-driven, never hardcoded.** Every number on the site (ASR, benign pass rate, call counts, latency) is read from `results.json`. While you use mock data, a visible **"SAMPLE DATA"** badge shows on every page. Removing it is a submission checklist item.
2. **Replay-first.** The whole site must work from static JSON with no backend. The backend only adds the live Try-to-break-it.
3. **Degrade gracefully.** If the API is down or the budget is exhausted, the site switches to replay and says so plainly. It never shows a broken page.
4. **Honest claims.** Do not show Finch (not integrated). Do not claim secrets detection. Show real latency (11–17 s per handoff) as a live progress view, not as something hidden.
5. **Voice and naming.** The product is **Trust Fall** (repo `trustfall-arena`, web app `trustfall-web`). The idea in one line: *agents trust each other blindly, so we test that trust.* Use the pun sparingly: the Break page can say "Take the trust fall" as a secondary line, but the main buttons stay literal ("Try to break it", "Watch the replay") so nothing is unclear. Before publishing, check the name is free on GitHub and Vercel (a similarly named open-source tool exists, so the repo name includes `-arena`).
6. **Looks designed, not templated.** One strong visual idea (a swarm of agents where one turns red and gets quarantined), a restrained palette, real typography, purposeful motion.

## 2. Stack and setup

| Concern | Choice |
|---|---|
| Framework | Vite + React 18 + TypeScript |
| Styling | Tailwind CSS with design tokens as CSS variables |
| Routing | React Router (`/`, `/arena`, `/break`, `/results`, `/about`, 404) |
| Data | TanStack Query for fetching and caching |
| Charts | Recharts for ASR bars; custom SVG for the swarm graph |
| Motion | Framer Motion, with `prefers-reduced-motion` support |
| Hosting | Vercel (free). Env: `VITE_API_URL`, `VITE_USE_MOCK` |
| Fonts | Google Fonts: Bricolage Grotesque (display), Inter (body), IBM Plex Mono (data and logs). Always set fallback stacks |

Setup steps:
```
npm create vite@latest trustfall-web -- --template react-ts
cd trustfall-web && npm i react-router-dom @tanstack/react-query recharts framer-motion
npm i -D tailwindcss postcss autoprefixer && npx tailwindcss init -p
```
Put the mock data in `public/mock/`: `results.json`, `events-R0.json`, `events-R1.json`, `events-R2.json`, `presets.json`, `leaderboard.json`. Ask Nehaa for the real files on Mon 9:00 PM, then flip `VITE_USE_MOCK=0`.

## 3. Contracts (mirrored from the backend plan)

### Event (replay and SSE)
Common fields: `t`, `run_id`, `round` (`R0|R1|R2|CH`), `seq`, `type`.
```json
{"type":"message","from":"red","to":"dispatcher","text":"…","attack_id":"A07"}
{"type":"gate","target":"worker","decision":"INJECTION","confidence":0.98,"blocked":true,"cached":false}
{"type":"agent_state","agent":"worker","state":"compromised"}
{"type":"judge","attack_id":"A07","goal":"leak","outcome":"succeeded","evidence":"canary in send_report"}
{"type":"patch","action":"applied","version":2,"summary":"…","benign_pass_rate":0.9}
{"type":"round_summary","asr":0.5,"asr_known":0.5,"asr_heldout":0.33,"benign_pass_rate":1.0,"gate_blocks":3,"llm_calls":14,"lyzr_calls":9}
{"type":"budget","llm_used":41,"llm_cap":200,"lyzr_used":9,"lyzr_cap":15}
```
- `agent_state.state`: `healthy | compromised | quarantined | restarting`
- `judge.outcome`: `succeeded | blocked_by_gate | resisted`; `goal`: `leak | poison | refund`
- `patch.action`: `proposed | applied | rejected | rolled_back`

### `results.json`
```ts
type Results = {
  run_id: string; generated_at: string;
  models: Record<string,string>;
  rounds: {
    id: "R0"|"R1"|"R2"; label: string; gate: boolean; patch_version: number;
    attacks: { id:string; title:string; category:string; owasp:string; goal:"leak"|"poison"|"refund";
               known:boolean; outcome:"succeeded"|"blocked_by_gate"|"resisted";
               gate: {decision:string; confidence:number} | null; latency_ms:number; llm_calls:number }[];
    asr:number; asr_known:number; asr_heldout:number|null;
    benign:{total:number; passed:number}; gate_blocks:number; llm_calls:number; lyzr_calls:number;
  }[];
  patches: { version:number; status:"applied"|"rejected"; reason?:string; summary:string; patch?:object }[];
  contagion?: { enabled:boolean; asr_without_guard:number; asr_with_guard:number };
  budget: { llm_calls:number; lyzr_calls:number };
};
```

### HTTP API (what the site calls)

| Call | Use |
|---|---|
| `GET /api/status` | Mode (`live`/`replay`), worker up/down, queue depth, budget |
| `GET /api/results` | All results |
| `GET /api/events/{round}` | Replay events |
| `GET /api/attacks/presets` | Preset attacks with cached outcomes per level |
| `POST /api/break` | Body `{level:"L0|L1|L2", goal:"leak|poison|refund", text, nickname?, share:boolean, preset_id?}` → `202 {attempt_id}` or `429 {reason:"rate|budget", retry_after}` |
| `GET /api/break/{id}/stream` | SSE: `step`, `verdict`, `error` |
| `GET /api/break/{id}` | Final verdict (permalink) |
| `GET /api/leaderboard` | Shared successful breaks and counters |
| `GET /api/reports/{round}.md` | Incident report download |

SSE events: `step {name:"gate|dispatcher|worker|referee", status:"running|done|blocked|error", ms}`, `verdict {outcome, stopped_by:"gate|worker|patch|none", goal, gate:{decision,confidence}, latency_ms}`, `error {reason:"timeout|budget|worker_down"}`.

**Note:** the browser `EventSource` only does GET, so the flow is `POST /api/break` → get `attempt_id` → open `EventSource(/api/break/{id}/stream)`.

## 4. Design system

**Concept:** a dark control-room look warmed by a diya-amber glow (a quiet nod to the Diwali hackathon theme). Red and Blue keep their semantic colors; amber is the Gate and the "defended" moment.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0B0D14` | Page background |
| `--surface` | `#12151F` | Cards |
| `--line` | `#232838` | Borders |
| `--text` | `#E8EAF2` | Body |
| `--muted` | `#8B93A7` | Secondary text |
| `--red` | `#FF4D5E` | Red agent, attacks, compromised |
| `--blue` | `#4DA3FF` | Blue agent, patches |
| `--amber` | `#FFB547` | Lyzr gate, blocked, glow |
| `--green` | `#3DDC97` | Healthy, benign pass |

Type scale: hero 64–72 px (clamp for mobile), H2 40, H3 24, body 17–18, mono 14. Spacing: 8 px grid, generous section padding (96–128 px desktop). Radii 14 px cards, 999 px pills.

Motion rules: one hero animation, short transitions (150–250 ms), amber pulse when the gate blocks, red flare when a node is compromised, soft fade-in on scroll. Everything respects `prefers-reduced-motion` (swap animation for static states).

Avoid: purple-blue gradient hero, generic glass cards everywhere, emoji as icons, stock illustrations, walls of centered text. Use simple custom SVG icons.

## 5. Information architecture

| Route | Purpose | Priority |
|---|---|---|
| `/` | Landing: pitch, hero, proof, CTA | P0 |
| `/arena` | Replay of the Red/Blue rounds, patch diff, rollback | P0 |
| `/break` | Try-to-break-it | P0 (presets), P1 (live) |
| `/results` | Benchmark: ASR, categories, benign rate, held-out, downloads | P1 |
| `/about` | Safety statement, sponsor stack, team, repo and hackathon links | P1 |

Global: sticky nav (logo, Arena, Break, Results, About, GitHub), footer, a **status pill** showing `LIVE` / `REPLAY` from `/api/status`, and the SAMPLE DATA badge when mock data is on.

## 6. Page specs

### 6.1 Landing `/`

| # | Section | Content and behavior |
|---|---|---|
| 1 | **Nav** | Logo mark, links, status pill, "Try to break it" button |
| 2 | **Hero** | Headline: *"Your agents trust each other. Let's test that."* Subhead: *"Trust Fall attacks a live multi-agent system, patches it, and proves the fix. Built on BAND, Agent37 and Lyzr."* Buttons: **Try to break it** (primary → `/break`), **Watch the replay** (→ `/arena`). Right side: the **SwarmGraph** hero animation (below) |
| 3 | **Proof strip** | Four big numbers from `results.json`: ASR R0 → R2, benign pass rate, held-out ASR, attacks run. Each counts up on scroll |
| 4 | **The problem** | Three short cards: agents pass messages with no human in the loop; one poisoned note persists in memory; a compromised agent contaminates the next one |
| 5 | **How it works** | Four steps with a looping diagram: **Attack** (Red) → **Gate** (Lyzr) → **Patch** (Blue + Referee) → **Retest**. Each step links to the matching Arena moment |
| 6 | **Architecture** | Interactive diagram: Dispatcher, Worker (Agent37), Red, Blue, Analyst, Referee, Gate. Hover or tap a node to see its role and the sponsor tool behind it |
| 7 | **Results preview** | ASR bars R0 → R1 → R2 plus the benign line ("normal tickets still pass: X/10"). Link to `/results` |
| 8 | **Contagion** | Short animation: poisoned Worker report reaches the Analyst; with guard it stops. Show only if `contagion.enabled` |
| 9 | **Try it teaser** | A mini input with three preset chips that jump to `/break` with the preset selected |
| 10 | **Sponsor stack** | Cards for BAND, Agent37, Lyzr, AdaL, each stating the concrete job it does (no logo walls without content) |
| 11 | **Safety note** | "Every target and secret is fake. The only system attacked is our own demo agent." |
| 12 | **Footer** | Repo, hackathon, team, built-with line |

**SwarmGraph (hero and arena visual):** an SVG graph with nodes Dispatcher, Worker, Red, Blue, Gate (and Analyst when enabled). Packets travel along edges. A reducer turns events into visual states: `message` → packet animation; `gate` blocked → amber pulse at the gate and the packet dies; `agent_state: compromised` → node turns red; `quarantined` → node dims with a ring; `patch applied` → Blue pulse and the node returns to healthy. On the landing page it loops a short scripted sequence from the sample events.

### 6.2 Arena `/arena`

Layout: top bar (round tabs **R0 / R1 / R2**, play/pause, speed 1x / 4x, scrub bar), left **SwarmGraph** (large), right **Event log** (mono, filter by type), bottom **round summary** (ASR, benign, gate blocks, call counts).

- Replay engine loads `events` for the selected round and feeds them to the reducer with timing from `t` (scaled by speed).
- Tabs below the graph: **Attacks** (table with outcome chips and OWASP tags), **Patch** (diff of `patch.json` between versions, shown as a readable before/after), **Rollback** (patch versions with `applied` / `rejected` and the reason, e.g. "benign pass 60% < 90%").
- If the rollback demo is shown, label it clearly as a safety test.
- Live-data badge shows counters from `budget` events.

### 6.3 Try-to-break-it `/break`

**Flow:**
1. **Pick a level** (three cards): *L0 No defense*, *L1 Lyzr gate*, *L2 Gate + Blue's patch*. Each card shows its current block rate from the recorded run.
2. **Pick a goal:** *Leak the canary*, *Plant a poison note in memory*, (P2) *Make the Analyst issue a refund*. One line explains what counts as a win.
3. **Write the attack** (ticket text, 500 chars, live counter) or choose a **preset** from a dropdown (shows category and OWASP tag). Optional nickname, and an opt-in checkbox *"Share my attack on the Hall of Breaks"* (off by default).
4. **Submit.** The pipeline stepper animates: **Gate → Dispatcher → Worker (Agent37) → Referee**, each with a spinner, duration, and state (done, blocked, error). Show an honest note: *"Handoffs take 10–20 seconds."*
5. **Verdict card:** `You broke it` / `Blocked at the gate (98% confidence)` / `The Worker resisted` / `Patch stopped it`. Include the layer that decided, the goal, latency, and the canary or memory evidence for a win. Buttons: *Try again*, *Try a harder level*, *Copy result link*.
6. **Hall of Breaks:** list of shared successful attacks (nickname, level, goal, time). Attack text is hidden behind a "reveal" and rendered as **escaped plain text**. A live counter shows attempts and the break rate per level.

**States to build (all P0 for this page):**
- *Preset attempt:* replays cached result instantly, labeled "Replayed from the recorded run".
- *Live attempt:* only when `/api/status.mode === "live"` and the worker is up.
- *Queued:* "N attempts ahead of you".
- *429 rate limit:* show `retry_after` and offer presets.
- *429 budget:* switch to replay mode with an explanation ("Today's free quota is used up. Presets still work.").
- *Timeout or worker down:* friendly error, offer presets.
- *API unreachable:* page loads in replay mode, no console errors.

**Client behavior:** disable submit while an attempt runs; clamp input length; trim whitespace; never render user text as HTML (React escapes by default; do not use `dangerouslySetInnerHTML`); include a hidden honeypot field the backend expects to stay empty.

### 6.4 Results `/results`

- **Round chart:** ASR per round (grouped bars: known vs held-out), benign pass rate line.
- **By category:** heatmap or small multiples of outcome by attack category and round, with OWASP LLM Top 10 tags (`LLM01`, `LLM02`, `LLM04`, `LLM06`, `LLM07`).
- **Held-out panel:** "Attacks the defender never saw" with its own ASR.
- **Trade-off panel:** security vs usability (ASR down, benign pass rate steady).
- **Patch history:** versions and statuses.
- **Cost panel:** LLM and Lyzr calls, caching hits. Shows we ran within free tiers.
- **Downloads:** `results.json`, `R0/R1/R2` incident reports (`/api/reports/{round}.md`), link to repo.

### 6.5 About `/about`

Safety statement (all fake targets), how the sponsors are used (one paragraph each), team, links (repo, hackathon, demo video), and a short "what we did not do" note (e.g., Finch not integrated, secrets detection not separately validated) if space allows.

## 7. Components

`Nav`, `StatusPill`, `SampleBadge`, `Hero`, `StatCounter`, `SwarmGraph` (+ `useSwarmReducer`), `StepCard`, `ArchitectureDiagram`, `RoundTabs`, `ReplayControls`, `EventLog`, `AttackTable`, `PatchDiff`, `AsrChart`, `CategoryHeatmap`, `LevelCard`, `GoalPicker`, `AttackComposer`, `PipelineStepper`, `VerdictCard`, `HallOfBreaks`, `SponsorCard`, `Footer`, `ErrorState`, `EmptyState`, `Skeleton`.

## 8. Data layer

```
src/
  api/        client.ts (fetch wrapper, mock switch)  types.ts (from section 3)
  hooks/      useResults.ts useStatus.ts useEvents.ts useBreak.ts useReplay.ts
  state/      swarmReducer.ts
  components/ pages/ styles/ assets/
```

- `client.ts`: if `VITE_USE_MOCK=1`, read from `/mock/*.json`; otherwise `VITE_API_URL`. Timeouts and one retry for GETs.
- `useStatus` polls `/api/status` every 15 s and drives the status pill and the live/replay decision.
- **SSE hook:**
```ts
export function useAttemptStream(id?: string) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!id) return;
    const es = new EventSource(`${API}/api/break/${id}/stream`);
    es.addEventListener("step", e => setSteps(s => [...s, JSON.parse((e as MessageEvent).data)]));
    es.addEventListener("verdict", e => { setVerdict(JSON.parse((e as MessageEvent).data)); es.close(); });
    es.addEventListener("error", e => { setError("connection"); es.close(); });
    return () => es.close();
  }, [id]);
  return { steps, verdict, error };
}
```
- **Swarm reducer:** state is `{agents: Record<string,"healthy"|"compromised"|"quarantined"|"restarting">, packets: Packet[], counters}`. Handle each event `type` from section 3. Keep it pure so replay can scrub back and forth by re-reducing from the start.
- Replay engine: sort by `seq`, schedule with `setTimeout` scaled by speed, support pause and seek.

## 9. Accessibility, responsiveness, performance

- Contrast at least 4.5:1 for text on all surfaces. Visible focus rings. Full keyboard use on `/break`.
- Verdict and pipeline updates go in an `aria-live="polite"` region. Charts have text equivalents (a table toggle).
- Reduced motion: static graph states and no count-up.
- Responsive: desktop-first, but every page must work at 390 px (the graph becomes a vertical stack; the event log collapses behind a tab).
- Performance: lazy-load routes and the graph/chart bundles, preload display fonts, images as SVG or optimized WebP, target LCP under 2.5 s on the Vercel deployment.
- SEO and sharing: title, description, Open Graph image (a static render of the hero), favicon, 404 page.

## 10. Build phases (≈ 22–26 h; use Antigravity for scaffolding, you own the design decisions)

| Phase | Work | Acceptance | Est. |
|---|---|---|---|
| F0 | Vite app, Tailwind tokens, fonts, router, API client with mock switch, mock data in `public/mock/` | Routes render with sample data and the SAMPLE badge | 1.5 h |
| F1 | Design system: tokens, type, buttons, cards, nav, footer, status pill | Style sheet page looks consistent | 2 h |
| F2 | **SwarmGraph and reducer** | Replaying mock R1 shows packet, gate block, compromised, quarantined | 4 h |
| F3 | **Landing** sections 1–7 and 10–12 | Reads well on desktop and 390 px | 4 h |
| F4 | **Arena** (tabs, replay controls, log, attack table, summary) | Scrub, speed, round switch all work | 3.5 h |
| F5 | **Break** with presets and all states using mock API | Every state in 6.3 is reachable | 4 h |
| F6 | **Results** page and charts | Numbers match `results.json` | 2.5 h |
| F7 | Contagion section, About, Hall of Breaks, patch diff and rollback view | Visible only when the data exists | 2.5 h |
| F8 | **Wire real API**, live attempts via SSE, 429/budget/timeout paths | One live attempt per level works on the deployed site | 2 h |
| F9 | A11y, mobile, performance, OG image, remove SAMPLE badge | Lighthouse a11y ≥ 90, no console errors | 2 h |

**Cut lines (if time runs short):** F7 extras → Results charts become a simple table → Landing sections 6 and 8 → live attempts (keep presets). Never cut: Hero + SwarmGraph, Arena replay, Break with presets.

## 11. Deployment

1. Push the web app to its own folder or repo, connect to Vercel, set `VITE_API_URL` (from Nehaa, Tue 11:00 AM) and `VITE_USE_MOCK=0`.
2. Backend must allow your Vercel domain in CORS (`ALLOWED_ORIGINS`). Tell Nehaa the exact domain.
3. Test on a phone and on a second browser profile.
4. Use this URL for **Deployed demo URL** on the submission form.
5. If the API is down at judging time, the site must still look complete in replay mode (test it by pointing `VITE_API_URL` at a bad URL).

## 12. QA checklist

- [ ] No hardcoded stats; all numbers come from `results.json`
- [ ] SAMPLE DATA badge removed after real data is loaded
- [ ] Preset attempt works with the API offline
- [ ] Live attempt works at L0, L1, L2 (when the backend is up)
- [ ] 429 rate and budget messages tested
- [ ] User text never rendered as HTML
- [ ] Works at 390 px and 1440 px; keyboard-only run-through of `/break`
- [ ] Reduced motion tested
- [ ] No Finch logo or claim; no claim about secrets detection
- [ ] OG image and favicon set; 404 page exists
- [ ] Safety note visible on the landing page and `/about`

## 13. Submission and demo (your part)

- **Deployed demo URL:** the Vercel link.
- **Sponsor answers:** write them from the real run. BAND: swarm and handoffs. Agent37: sandbox, persistent memory, boot hook. Lyzr: gate service. AdaL: only what you actually used (the demo video). Finch: honest "evaluated, not integrated" if the field is required.
- **Screen-recorded pitch** (recorded in the browser on the submit page, 1 minute minimum, screen plus camera and mic): rehearse first because it cannot be edited. Suggested 90-second flow:
  1. 0:00 Hero and one-line problem.
  2. 0:15 Arena R0: attack succeeds (compromised node).
  3. 0:35 R1: Lyzr gate blocks blunt attacks, Red goes indirect.
  4. 0:50 Blue's patch, rollback test, R2: ASR drops, benign tickets still pass.
  5. 1:10 `/break`: one live attempt on L2 (or a preset if the API is slow).
  6. 1:25 Results page and the safety note.
- Ask in the hackathon WhatsApp group whether the separate 2-minute AdaL demo video is also required and where it goes.
- Final: confirm the repo is public, the demo URL opens for someone logged out, and submit by 6:00 PM IST on Tue 24 Nov (deadline 10:00 PM).
