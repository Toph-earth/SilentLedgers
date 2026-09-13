import { useSummary } from '../hooks/useSummary.js';

const PATTERNS = [
  {
    type: 'Structuring',
    desc: 'Many accounts each send an amount just under the reporting threshold into one destination.',
  },
  {
    type: 'Layering',
    desc: 'Funds pass through a chain of accounts, losing a little value at each hop to obscure origin.',
  },
  {
    type: 'Round-tripping',
    desc: 'Money leaves an account and returns to it a few hops later, netting near-zero real activity.',
  },
];

function TeaserStat({ label, value }) {
  return (
    <div className="flex flex-col items-center gap-1 border-l border-ink-600 px-6 first:border-l-0">
      <span className="font-mono text-2xl text-parchment-100">{value}</span>
      <span className="text-xs text-parchment-500">{label}</span>
    </div>
  );
}

export default function LandingPage({ onEnter }) {
  const { status, data } = useSummary();

  return (
    <div className="flex h-screen flex-col items-center justify-center overflow-y-auto bg-ink-950 px-6 py-16">
      <div className="w-full max-w-2xl text-center">
        <span className="font-mono text-xs uppercase tracking-widest text-brass-500">
          transaction network analysis
        </span>
        <h1 className="mt-3 font-serif text-4xl text-parchment-100 sm:text-5xl">SilentLegders</h1>
        <p className="mx-auto mt-4 max-w-lg text-sm leading-relaxed text-parchment-500">
          No single transaction looks wrong. The crime only shows up as a shape in the
          network — a hub, a chain, a loop. SilentLegders finds that shape.
        </p>

        <button
          onClick={onEnter}
          className="mt-8 rounded border border-brass-600 bg-ink-800 px-6 py-2.5 text-sm text-brass-400 transition-colors hover:bg-ink-700"
        >
          Try it out →
        </button>

        {status === 'success' && data && (
          <div className="mt-10 flex justify-center rounded border border-ink-600 bg-ink-900 py-4">
            <TeaserStat label="accounts" value={data.totalAccounts} />
            <TeaserStat label="flagged" value={data.flaggedAccounts} />
            <TeaserStat label="active patterns" value={data.activePatterns} />
          </div>
        )}

        <div className="mt-12 grid gap-3 text-left sm:grid-cols-3">
          {PATTERNS.map((p) => (
            <div key={p.type} className="rounded border border-ink-600 bg-ink-900 p-4">
              <div className="font-serif text-sm text-parchment-100">{p.type}</div>
              <p className="mt-1.5 text-xs leading-relaxed text-parchment-500">{p.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
