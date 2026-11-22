/**
 * Tiny API client for Trust Fall.
 * Switches between live FastAPI backend and web/public/mock/ JSON files via VITE_USE_MOCK.
 */

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== 'false';
const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export async function fetchResults() {
  if (USE_MOCK) {
    const res = await fetch('/mock/results.json');
    return res.json();
  }
  const res = await fetch(`${BASE_URL}/api/results`);
  return res.json();
}

export async function fetchEvents(roundId: string) {
  if (USE_MOCK) {
    const res = await fetch(`/mock/events-${roundId}.json`);
    return res.json();
  }
  const res = await fetch(`${BASE_URL}/api/events/${roundId}`);
  return res.json();
}

export async function fetchPresets() {
  if (USE_MOCK) {
    const res = await fetch('/mock/presets.json');
    return res.json();
  }
  const res = await fetch(`${BASE_URL}/api/attacks/presets`);
  return res.json();
}

export async function fetchLeaderboard() {
  if (USE_MOCK) {
    const res = await fetch('/mock/leaderboard.json');
    return res.json();
  }
  const res = await fetch(`${BASE_URL}/api/leaderboard`);
  return res.json();
}

export async function submitBreakAttempt(payload: {
  level: string;
  goal: string;
  text: string;
  nickname?: string;
  share: boolean;
  preset_id?: string;
}) {
  if (USE_MOCK) {
    return {
      attempt_id: `mock-att-${Date.now()}`,
      status: 'accepted',
    };
  }
  const res = await fetch(`${BASE_URL}/api/break`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
}
