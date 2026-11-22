import React, { useState, useEffect } from 'react';
import { fetchPresets, fetchLeaderboard, submitBreakAttempt } from '../api/client';

export const Break: React.FC = () => {
  const [presets, setPresets] = useState<any[]>([]);
  const [leaderboard, setLeaderboard] = useState<any>(null);
  const [level, setLevel] = useState<'L0' | 'L1' | 'L2'>('L1');
  const [text, setText] = useState('');
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    fetchPresets().then(setPresets).catch(console.error);
    fetchLeaderboard().then(setLeaderboard).catch(console.error);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setStatus('Submitting attempt...');
    try {
      const res = await submitBreakAttempt({
        level,
        goal: 'leak',
        text,
        share: true,
      });
      setStatus(`Attempt registered: ${res.attempt_id}`);
    } catch (err: any) {
      setStatus(`Error: ${err.message}`);
    }
  };

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-red-400">Try To Break It</h1>
        <p className="text-slate-400">Test the sandboxed agent across defense tiers (L0, L1, L2)</p>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-6">
          <form onSubmit={handleSubmit} className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
            <div>
              <label className="block text-sm font-medium mb-1">Defense Level</label>
              <div className="flex gap-4">
                {(['L0', 'L1', 'L2'] as const).map((lvl) => (
                  <label key={lvl} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="radio"
                      name="level"
                      value={lvl}
                      checked={level === lvl}
                      onChange={() => setLevel(lvl)}
                      className="accent-red-500"
                    />
                    <span className="font-semibold">{lvl}</span>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Injection Payload (max 500 chars)</label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={500}
                rows={4}
                placeholder="Enter prompt injection or jailbreak test..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-sm focus:border-red-500 focus:outline-none"
              />
              <span className="text-xs text-slate-500 float-right">{text.length}/500</span>
            </div>

            <button
              type="submit"
              className="px-6 py-2.5 bg-red-600 hover:bg-red-700 text-white font-medium rounded-lg transition"
            >
              Launch Attack
            </button>

            {status && (
              <div className="p-3 bg-slate-950 border border-slate-800 rounded text-sm text-yellow-300">
                {status}
              </div>
            )}
          </form>

          <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-3">
            <h3 className="font-bold text-lg">Presets</h3>
            <div className="grid gap-2">
              {presets.map((p) => (
                <button
                  key={p.id}
                  onClick={() => setText(p.text)}
                  className="text-left p-3 rounded bg-slate-950 hover:bg-slate-800/80 border border-slate-800 transition"
                >
                  <div className="font-semibold text-sm text-slate-200">{p.title}</div>
                  <div className="text-xs text-slate-400 truncate">{p.text}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
          <h3 className="font-bold text-lg text-emerald-400">Leaderboard</h3>
          {leaderboard ? (
            <div className="space-y-3">
              <div className="text-sm text-slate-400">
                Total Attempts: <span className="text-white font-bold">{leaderboard.total_attempts}</span>
              </div>
              <div className="space-y-2">
                {leaderboard.entries?.map((e: any, idx: number) => (
                  <div key={idx} className="p-2.5 rounded bg-slate-950 border border-slate-800 text-xs">
                    <div className="font-semibold text-red-300">@{e.nickname}</div>
                    <div className="text-slate-400">{e.attack_title}</div>
                    <div className="text-slate-500 mt-1">Level: {e.level} • {e.latency_ms}ms</div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="text-xs text-slate-500">Loading leaderboard...</div>
          )}
        </div>
      </div>
    </div>
  );
};
