// Generated mock data. Shapes here are the source of truth for
// BACKEND_CONTRACT.md — the backend must match what this file returns.
//
// Three named clusters carry the demo:
//   ACC_001  structuring hub   — many sub-threshold inbound transfers land here
//   ACC_042  layering chain    — money hops through a short chain, losing a bit each time
//   ACC_117  round-trip loop   — funds leave and return to the same account
// ACC_205 is a low-risk peripheral account that feeds the structuring hub,
// used in GUIDE.md's worked example to show what a "normal-looking" node is.

const NAMES = [
  'Meridian Holdings', 'Coastal Trade Co', 'Nightingale LLC', 'Pinecrest Partners',
  'Vellum Imports', 'Anchor & Vine', 'Basalt Logistics', 'Harborlight Retail',
  'Quill Consulting', 'Redgate Foods', 'Solstice Freight', 'Marrow Capital',
  'Foxglove Studio', 'Brackish Traders', 'Ivorywood Group', 'Cinder Supply Co',
];

const COUNTRIES = ['US', 'US', 'US', 'UK', 'AE', 'SG', 'CY', 'PA'];

function seededRand(seed) {
  let s = seed % 2147483647;
  if (s <= 0) s += 2147483646;
  return function next() {
    s = (s * 16807) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

const rand = seededRand(42);

function pick(arr) {
  return arr[Math.floor(rand() * arr.length)];
}

function buildAccount(id, overrides = {}) {
  const base = {
    id,
    name: overrides.name || pick(NAMES),
    country: overrides.country || pick(COUNTRIES),
    riskScore: 20,
    flagged: false,
    totalVolume30d: Math.round(4000 + rand() * 40000),
  };
  return { ...base, ...overrides };
}

// --- Accounts -----------------------------------------------------------

const ACCOUNTS = [
  buildAccount('ACC_001', { name: 'Coastal Trade Co', riskScore: 91, flagged: true, totalVolume30d: 184320 }),
  buildAccount('ACC_010', { riskScore: 62, flagged: true, totalVolume30d: 9450 }),
  buildAccount('ACC_011', { riskScore: 58, flagged: true, totalVolume30d: 8800 }),
  buildAccount('ACC_012', { riskScore: 64, flagged: true, totalVolume30d: 9100 }),
  buildAccount('ACC_013', { riskScore: 55, flagged: true, totalVolume30d: 8600 }),
  buildAccount('ACC_014', { riskScore: 51, flagged: false, totalVolume30d: 8200 }),
  buildAccount('ACC_205', { name: 'Foxglove Studio', riskScore: 34, flagged: false, totalVolume30d: 7100 }),

  buildAccount('ACC_042', { name: 'Marrow Capital', riskScore: 87, flagged: true, totalVolume30d: 152000 }),
  buildAccount('ACC_043', { riskScore: 79, flagged: true, totalVolume30d: 141500 }),
  buildAccount('ACC_044', { riskScore: 74, flagged: true, totalVolume30d: 133800 }),
  buildAccount('ACC_045', { riskScore: 68, flagged: true, totalVolume30d: 126200 }),

  buildAccount('ACC_117', { name: 'Brackish Traders', riskScore: 83, flagged: true, totalVolume30d: 96500 }),
  buildAccount('ACC_118', { riskScore: 71, flagged: true, totalVolume30d: 94200 }),
  buildAccount('ACC_119', { riskScore: 69, flagged: true, totalVolume30d: 92800 }),
];

// A tail of ordinary, low-risk accounts so the dashboard doesn't look like
// every account is dirty. Also exercises the node cap in the graph.
for (let i = 1; i <= 30; i++) {
  const id = `ACC_${String(200 + i).padStart(3, '0')}`;
  if (ACCOUNTS.find((a) => a.id === id)) continue;
  ACCOUNTS.push(buildAccount(id, { riskScore: Math.round(5 + rand() * 30), flagged: false }));
}

// --- Patterns -------------------------------------------------------------

const PATTERNS = [
  {
    id: 'P-STRUCT-1',
    type: 'structuring',
    label: 'Structuring into ACC_001',
    summary: '5 accounts each send transfers just under the $10,000 reporting threshold into a single receiving account within a 36-hour window.',
    riskScore: 91,
    memberAccounts: ['ACC_001', 'ACC_010', 'ACC_011', 'ACC_012', 'ACC_013', 'ACC_014'],
    detectedAt: '2026-09-08T14:12:00Z',
  },
  {
    id: 'P-LAYER-1',
    type: 'layering',
    label: 'Layering chain ACC_042 → ACC_045',
    summary: 'Funds pass through a 4-hop chain of accounts, each hop retaining roughly 92-96% of the prior amount, consistent with layering to obscure origin.',
    riskScore: 87,
    memberAccounts: ['ACC_042', 'ACC_043', 'ACC_044', 'ACC_045'],
    detectedAt: '2026-09-09T03:41:00Z',
  },
  {
    id: 'P-ROUND-1',
    type: 'round_tripping',
    label: 'Round-trip loop via ACC_117',
    summary: 'Funds leave ACC_117, pass through two intermediaries, and return to ACC_117 within 9 days, netting close to zero economic activity.',
    riskScore: 83,
    memberAccounts: ['ACC_117', 'ACC_118', 'ACC_119'],
    detectedAt: '2026-09-09T19:02:00Z',
  },
];

// --- Graph ------------------------------------------------------------

function edge(id, source, target, amount, count) {
  return { id, source, target, data: { amount, count } };
}

const ALL_EDGES = [
  // Structuring: many small inbound transfers converging on ACC_001
  edge('e-010-001', 'ACC_010', 'ACC_001', 9450, 1),
  edge('e-011-001', 'ACC_011', 'ACC_001', 8800, 1),
  edge('e-012-001', 'ACC_012', 'ACC_001', 9100, 1),
  edge('e-013-001', 'ACC_013', 'ACC_001', 8600, 1),
  edge('e-014-001', 'ACC_014', 'ACC_001', 8200, 1),
  edge('e-205-010', 'ACC_205', 'ACC_010', 4100, 3),

  // Layering: a chain, amount shrinking slightly at each hop
  edge('e-042-043', 'ACC_042', 'ACC_043', 152000, 1),
  edge('e-043-044', 'ACC_043', 'ACC_044', 141500, 1),
  edge('e-044-045', 'ACC_044', 'ACC_045', 133800, 1),

  // Round-tripping: a loop back to the origin
  edge('e-117-118', 'ACC_117', 'ACC_118', 96500, 1),
  edge('e-118-119', 'ACC_118', 'ACC_119', 94200, 1),
  edge('e-119-117', 'ACC_119', 'ACC_117', 92800, 1),
];

// Sparse, low-amount noise edges among the ordinary tail accounts so the
// unfiltered graph looks like a real account population, not just three
// isolated clusters.
const TAIL_IDS = ACCOUNTS.filter((a) => !a.flagged).map((a) => a.id);
for (let i = 0; i < 18; i++) {
  const a = pick(TAIL_IDS);
  let b = pick(TAIL_IDS);
  if (b === a) b = TAIL_IDS[(TAIL_IDS.indexOf(a) + 1) % TAIL_IDS.length];
  ALL_EDGES.push(edge(`e-noise-${i}`, a, b, Math.round(200 + rand() * 3000), 1));
}

function toFlowNode(account) {
  return {
    id: account.id,
    type: 'risk',
    data: {
      label: account.id,
      accountName: account.name,
      risk: account.riskScore,
      flagged: account.flagged,
    },
    position: { x: 0, y: 0 }, // overwritten by dagre layout on the client
  };
}

// --- Public mock API (mirrors BACKEND_CONTRACT.md exactly) --------------

export function getSummary() {
  const flagged = ACCOUNTS.filter((a) => a.flagged);
  return {
    totalAccounts: ACCOUNTS.length,
    flaggedAccounts: flagged.length,
    activePatterns: PATTERNS.length,
    totalFlaggedVolume30d: flagged.reduce((sum, a) => sum + a.totalVolume30d, 0),
    highestRiskScore: Math.max(...ACCOUNTS.map((a) => a.riskScore)),
    generatedAt: new Date().toISOString(),
  };
}

export function getAccounts({ minRisk } = {}) {
  const min = Number.isFinite(minRisk) ? minRisk : 0;
  return ACCOUNTS
    .filter((a) => a.riskScore >= min)
    .sort((a, b) => b.riskScore - a.riskScore)
    .map((a) => ({ ...a }));
}

export function getPatterns() {
  return PATTERNS.map((p) => ({ ...p }));
}

export function getGraph({ patternId } = {}) {
  let nodeIds;
  let edges;

  if (patternId) {
    const pattern = PATTERNS.find((p) => p.id === patternId);
    if (!pattern) {
      return { nodes: [], edges: [], meta: { totalAccounts: 0, truncated: false } };
    }
    nodeIds = new Set(pattern.memberAccounts);
    edges = ALL_EDGES.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
  } else {
    nodeIds = new Set(ACCOUNTS.map((a) => a.id));
    edges = ALL_EDGES;
  }

  const nodes = ACCOUNTS.filter((a) => nodeIds.has(a.id)).map(toFlowNode);

  return {
    nodes,
    edges,
    meta: { totalAccounts: nodes.length, truncated: false },
  };
}

export function getAccountTimeline(accountId) {
  const account = ACCOUNTS.find((a) => a.id === accountId);
  if (!account) {
    const err = new Error(`Unknown account ${accountId}`);
    err.isAxiosError = true;
    err.response = { status: 404, data: { message: `Unknown account ${accountId}` } };
    throw err;
  }

  const days = 30;
  const points = [];
  const localRand = seededRand(accountId.charCodeAt(accountId.length - 1) * 97 + 7);
  const today = new Date('2026-09-11T00:00:00Z');

  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - i);
    let volume = Math.round(150 + localRand() * 900);

    // Flagged accounts get a visible spike in the last third of the window,
    // so the chart tells the same story as the graph and pattern cards.
    if (account.flagged && i <= 9) {
      volume += Math.round(2500 + localRand() * 4000);
    }

    points.push({
      date: d.toISOString().slice(0, 10),
      volume,
      transactionCount: Math.round(1 + localRand() * (account.flagged ? 6 : 2)),
    });
  }

  return { accountId, points };
}
