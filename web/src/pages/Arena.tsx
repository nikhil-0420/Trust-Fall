import React, { useState, useEffect } from 'react';
import { fetchEvents } from '../api/client';

export const Arena: React.FC = () => {
  const [round, setRound] = useState<'R0' | 'R1' | 'R2'>('R0');
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    fetchEvents(round).then(setEvents).catch(console.error);
  }, [round]);

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-6">
      <div className="flex justify-between items-center border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-3xl font-bold">Arena Event Replay</h1>
          <p className="text-slate-400 text-sm">Inspecting round execution stream</p>
        </div>
        <div className="flex gap-2">
          {(['R0', 'R1', 'R2'] as const).map((r) => (
            <button
              key={r}
              onClick={() => setRound(r)}
              className={`px-4 py-1.5 rounded-lg font-medium transition ${
                round === r
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              Round {r}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 font-mono text-sm max-h-[600px] overflow-y-auto space-y-2">
        {events.length === 0 ? (
          <div className="text-slate-500 text-center py-8">Loading events...</div>
        ) : (
          events.map((e, idx) => (
            <div key={idx} className="p-2.5 rounded bg-slate-950/60 border border-slate-800/80 flex items-start gap-3">
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 uppercase font-semibold">
                {e.type}
              </span>
              <div className="flex-1">
                {e.type === 'message' && (
                  <p className="text-slate-300">
                    <span className="text-blue-400 font-semibold">{e.from}</span> &rarr;{' '}
                    <span className="text-emerald-400 font-semibold">{e.to}</span>: {e.text}
                  </p>
                )}
                {e.type === 'gate' && (
                  <p className={e.blocked ? 'text-red-400' : 'text-emerald-400'}>
                    Gate Decision: <strong>{e.decision}</strong> (confidence: {(e.confidence * 100).toFixed(0)}%, blocked: {String(e.blocked)})
                  </p>
                )}
                {e.type === 'judge' && (
                  <p className="text-yellow-400">
                    Verdict [{e.attack_id}]: <strong>{e.outcome}</strong> ({e.evidence})
                  </p>
                )}
                {e.type === 'patch' && (
                  <p className="text-purple-400">
                    Patch v{e.version} [{e.action}]: {e.summary}
                  </p>
                )}
                {e.type === 'round_summary' && (
                  <p className="text-cyan-300 font-bold">
                    Round Summary: ASR = {(e.asr * 100).toFixed(1)}%, Gate Blocks = {e.gate_blocks}
                  </p>
                )}
                {e.type === 'budget' && (
                  <p className="text-slate-400 text-xs">
                    Budget: LLM {e.llm_used}/{e.llm_cap}, Lyzr {e.lyzr_used}/{e.lyzr_cap}
                  </p>
                )}
                {e.type === 'agent_state' && (
                  <p className="text-slate-300">
                    Agent {e.agent} state: <strong className="text-emerald-400">{e.state}</strong>
                  </p>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
