import React from 'react';

export const About: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto py-8 px-4 space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-emerald-400">About Trust Fall</h1>
        <p className="text-slate-400">Adversarial evaluation & adaptive defense for multi-agent systems</p>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-4">
        <h2 className="text-xl font-bold text-slate-200">Sponsor Technologies</h2>
        <ul className="list-disc list-inside space-y-2 text-slate-300 text-sm">
          <li><strong>BAND:</strong> Swarm room coordination and real-time handoffs.</li>
          <li><strong>Agent37:</strong> MicroVM execution environment with persistent memory and restart hooks.</li>
          <li><strong>Lyzr:</strong> Pre-execution screening gate detecting prompt injections and adversarial inputs.</li>
          <li><strong>AdaL:</strong> Synthetic agent showcase and demonstration pipeline.</li>
        </ul>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 space-y-3">
        <h2 className="text-xl font-bold text-slate-200">Safety Disclaimer</h2>
        <p className="text-sm text-slate-400">
          All targets, canary tokens, and mock records in Trust Fall are completely synthetic (e.g. <code>CANARY-ab12cd-DEMO-ONLY</code>).
          Evaluation attacks target only our local sandboxed demonstration worker. No external systems, production APIs, or real private data are exposed.
        </p>
      </div>
    </div>
  );
};
