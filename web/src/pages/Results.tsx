import React, { useState, useEffect } from 'react';
import { fetchResults } from '../api/client';

export const Results: React.FC = () => {
  const [results, setResults] = useState<any>(null);

  useEffect(() => {
    fetchResults().then(setResults).catch(console.error);
  }, []);

  if (!results) {
    return <div className="max-w-5xl mx-auto py-12 px-4 text-center text-slate-500">Loading results...</div>;
  }

  return (
    <div className="max-w-5xl mx-auto py-8 px-4 space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-purple-400">Evaluation Results</h1>
        <p className="text-slate-400">Run: {results.run_id} {results.sample && '(Sample Dataset)'}</p>
      </div>

      <div className="grid md:grid-cols-3 gap-6">
        {results.rounds?.map((r: any) => (
          <div key={r.id} className="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div className="flex justify-between items-center">
              <span className="font-bold text-lg text-slate-200">{r.id}: {r.label}</span>
              <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                Patch v{r.patch_version}
              </span>
            </div>
            <div className="text-3xl font-extrabold text-blue-400">
              {(r.asr * 100).toFixed(1)}% <span className="text-sm font-normal text-slate-400">ASR</span>
            </div>
            <div className="text-xs text-slate-400 space-y-1">
              <div>Gate blocks: {r.gate_blocks}</div>
              <div>Benign pass: {r.benign?.passed}/{r.benign?.total}</div>
              <div>LLM calls: {r.llm_calls}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h2 className="text-xl font-bold text-slate-200">Defensive Patches</h2>
        <div className="space-y-3">
          {results.patches?.map((p: any) => (
            <div key={p.version} className="p-4 rounded-lg bg-slate-950 border border-slate-800">
              <div className="flex justify-between items-center mb-1">
                <span className="font-semibold text-slate-200">Version {p.version}</span>
                <span
                  className={`text-xs px-2 py-0.5 rounded uppercase font-bold ${
                    p.status === 'applied' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' : 'bg-red-950 text-red-400 border border-red-800'
                  }`}
                >
                  {p.status}
                </span>
              </div>
              <p className="text-sm text-slate-400">{p.summary}</p>
              {p.reason && <p className="text-xs text-red-400 mt-1">Reason: {p.reason}</p>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
