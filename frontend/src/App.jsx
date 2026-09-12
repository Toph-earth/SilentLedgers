import { useState } from 'react';

import LandingPage from './pages/LandingPage.jsx';
import KPIBar from './components/kpi/KPIBar.jsx';
import PatternList from './components/patterns/PatternList.jsx';
import TransactionGraph from './components/graph/TransactionGraph.jsx';
import TimelineChart from './components/timeline/TimelineChart.jsx';
import AccountTable from './components/accounts/AccountTable.jsx';


// Layout at 1280px (the demo resolution):
//   header            1280 x 72,  fixed
//   pattern list       260 wide,  fixed, own scroll, tabbed by pattern type
//   graph             flex-1 (~660), fixed height, pan/zoom internally, no page scroll
//   right rail         360 wide,  fixed, split 40/60 into timeline / account table
// See GUIDE.md section 3 for the derivation.

export default function App() {
  const [view, setView] = useState('dashboard'); // 'landing' | 'dashboard'
  const [selectedPatternId, setSelectedPatternId] = useState(null);
  const [selectedAccountId, setSelectedAccountId] = useState(null);

  // Bumped after a successful Regenerate/Upload (see DataControls) so
  // every region refetches. Not sent to the backend — it's purely a React
  // dependency-array trigger, kept in one place so no component has to
  // know *why* it's refetching.
  const [dataVersion, setDataVersion] = useState(0);

  if (view === 'landing') {
    return <LandingPage onEnter={() => setView('dashboard')} />;
  }

  return (
    <div className="flex h-screen flex-col bg-ink-950">
      <KPIBar onDataChanged={() => setDataVersion((v) => v + 1)} />
      <main className="flex min-h-0 flex-1">
        <section className="w-[260px] shrink-0 border-r border-ink-600 bg-ink-900">
          <PatternList
            selectedPatternId={selectedPatternId}
            onSelectPattern={setSelectedPatternId}
            dataVersion={dataVersion}
          />
        </section>

        <section className="min-w-0 flex-1 bg-ink-950">
          <TransactionGraph
            selectedPatternId={selectedPatternId}
            selectedAccountId={selectedAccountId}
            onSelectAccount={setSelectedAccountId}
            dataVersion={dataVersion}
          />
        </section>

        <section className="flex w-[360px] shrink-0 flex-col border-l border-ink-600 bg-ink-900">
          <div className="h-[38%] border-b border-ink-600">
            <TimelineChart accountId={selectedAccountId} />
          </div>
          <div className="h-[62%] min-h-0">
            <AccountTable
              selectedAccountId={selectedAccountId}
              onSelectAccount={setSelectedAccountId}
              dataVersion={dataVersion}
            />
          </div>
        </section>
      </main>
    </div>
  );
}
