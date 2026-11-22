import React from 'react';
import { Link } from 'react-router-dom';

export const Home: React.FC = () => {
  return (
    <div className="max-w-4xl mx-auto py-12 px-4 space-y-8">
      <div className="text-center space-y-4">
        <h1 className="text-5xl font-extrabold tracking-tight bg-gradient-to-r from-red-400 via-purple-300 to-blue-400 bg-clip-text text-transparent">
          Trust Fall
        </h1>
        <p className="text-xl text-slate-300">
          Your agents trust each other. Let's test that.
        </p>
      </div>

      <div className="grid md:grid-cols-2 gap-6 mt-8">
        <Link
          to="/arena"
          className="p-6 bg-slate-900 border border-slate-800 rounded-xl hover:border-blue-500 transition shadow-lg"
        >
          <h2 className="text-2xl font-bold text-blue-400 mb-2">Security Arena &rarr;</h2>
          <p className="text-slate-400">
            Watch Red and Blue agents battle through automated injection rounds (R0, R1, R2).
          </p>
        </Link>

        <Link
          to="/break"
          className="p-6 bg-slate-900 border border-slate-800 rounded-xl hover:border-red-500 transition shadow-lg"
        >
          <h2 className="text-2xl font-bold text-red-400 mb-2">Try-To-Break-It &rarr;</h2>
          <p className="text-slate-400">
            Submit custom prompt injections or select presets to test our sandboxed agent live.
          </p>
        </Link>

        <Link
          to="/results"
          className="p-6 bg-slate-900 border border-slate-800 rounded-xl hover:border-purple-500 transition shadow-lg"
        >
          <h2 className="text-2xl font-bold text-purple-400 mb-2">Results & Metrics &rarr;</h2>
          <p className="text-slate-400">
            Explore ASR progression curves, patch diffs, and contagion resistance graphs.
          </p>
        </Link>

        <Link
          to="/about"
          className="p-6 bg-slate-900 border border-slate-800 rounded-xl hover:border-emerald-500 transition shadow-lg"
        >
          <h2 className="text-2xl font-bold text-emerald-400 mb-2">Architecture & About &rarr;</h2>
          <p className="text-slate-400">
            Learn about BAND swarm coordination, Agent37 sandboxing, and Lyzr gate screening.
          </p>
        </Link>
      </div>
    </div>
  );
};
