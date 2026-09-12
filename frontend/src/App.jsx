import { useState } from 'react';

import KPIBar from './components/kpi/KPIBar.jsx';
import PatternList from './components/patterns/PatternList.jsx';
import TransactionGraph from './components/graph/TransactionGraph.jsx';
import TimelineChart from './components/timeline/TimelineChart.jsx';
import AccountTable from './components/accounts/AccountTable.jsx';
import { isMockMode } from './api/client.js';

// Layout at 1280px (the demo resolution):
//   header            1280 x 72,  fixed
//   pattern list       260 wide,  fixed, own scroll
//   graph             flex-1 (~660), fixed height, pan/zoom internally, no page scroll
//   right rail         360 wide,  fixed, split 40/60 into timeline / account table
// See GUIDE.md section 3 for the derivation.

export default function App() {
  const [selectedPatternId, setSelectedPatternId] = useState(null);
  const [selectedAccountId, setSelectedAccountId] = useState(null);

  return (
    <div className="flex h-screen flex-col bg-ink-950">
      <KPIBar />

      {isMockMode && (
        <div className="border-b border-ink-600 bg-ink-800 px-6 py-1 text-center text-[11px] text-brass-400">
          Mock data mode — set VITE_USE_MOCK=false in .env to use the live backend
        </div>
      )}

      <main className="flex min-h-0 flex-1">
        <section className="w-[260px] shrink-0 border-r border-ink-600 bg-ink-900">
          <PatternList selectedPatternId={selectedPatternId} onSelectPattern={setSelectedPatternId} />
        </section>

        <section className="min-w-0 flex-1 bg-ink-950">
          <TransactionGraph
            selectedPatternId={selectedPatternId}
            selectedAccountId={selectedAccountId}
            onSelectAccount={setSelectedAccountId}
          />
        </section>

        <section className="flex w-[360px] shrink-0 flex-col border-l border-ink-600 bg-ink-900">
          <div className="h-[38%] border-b border-ink-600">
            <TimelineChart accountId={selectedAccountId} />
          </div>
          <div className="h-[62%] min-h-0">
            <AccountTable selectedAccountId={selectedAccountId} onSelectAccount={setSelectedAccountId} />
          </div>
        </section>
      </main>
    </div>
  );
}
