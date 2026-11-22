import React from 'react';
import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Home } from './pages/Home';
import { Arena } from './pages/Arena';
import { Break } from './pages/Break';
import { Results } from './pages/Results';
import { About } from './pages/About';

const queryClient = new QueryClient();

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100">
          <header className="border-b border-slate-800 bg-slate-900/50 backdrop-blur sticky top-0 z-50">
            <div className="max-w-6xl mx-auto px-4 h-16 flex items-center justify-between">
              <Link to="/" className="text-xl font-bold tracking-tight text-white flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse"></span>
                Trust Fall
              </Link>
              <nav className="flex items-center gap-6 text-sm font-medium text-slate-400">
                <Link to="/arena" className="hover:text-white transition">Arena</Link>
                <Link to="/break" className="hover:text-white transition">Break</Link>
                <Link to="/results" className="hover:text-white transition">Results</Link>
                <Link to="/about" className="hover:text-white transition">About</Link>
              </nav>
            </div>
          </header>

          <main className="flex-1">
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/arena" element={<Arena />} />
              <Route path="/break" element={<Break />} />
              <Route path="/results" element={<Results />} />
              <Route path="/about" element={<About />} />
            </Routes>
          </main>

          <footer className="border-t border-slate-800 py-6 text-center text-xs text-slate-500">
            Trust Fall &bull; Hackathon Red-vs-Blue Security Arena for Multi-Agent Systems
          </footer>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
