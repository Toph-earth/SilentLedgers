# Build Guide — Silent Ledger Frontend

## 1. The frontend problem, restated

The person looking at this screen is a compliance analyst at a small bank or
fintech, or a judge at a hackathon standing in for one. They did not come to
watch a transaction list. They came because someone told them a set of
accounts are laundering money and they need to answer three questions fast:
which accounts, how confident should I be, and what do I do next (freeze,
escalate, ignore).

The mechanism that makes this hard: no single transaction looks wrong. A
$9,450 transfer is unremarkable. The crime is only visible as a shape —
five accounts converging on one, a chain that loses a little value at each
hop, a loop that returns to where it started. That shape only exists in the
network. A table of transactions, however well sorted, cannot show it. This
is the entire justification for React Flow being load-bearing rather than
decorative — if the graph were removed, the product would not be a lesser
version of itself, it would be a different, wrong product (a transaction
list with a risk column).

The "aha" moment is the instant the analyst looks at the graph after
clicking a pattern and the shape matches the pattern's name: five spokes
into a hub for structuring, a visibly thinning chain for layering, a closed
loop for round-tripping. If the graph is drawn but the shape isn't legible
at a glance, the whole product has failed even if every number is correct.

Easy-to-overlook parts:

- The analyst does not start by reading account IDs off a list. They start
  from the KPI strip (is there a problem at all?), then the pattern list
  (what kind of problem?), then the graph (which accounts, exactly?). The
  layout has to support that order, not fight it by putting the graph
  behind a click.
- A single boring account sitting next to a structuring hub is part of the
  story too — it's the "before" that makes the "after" legible. ACC_205 in
  the worked example (section 5) exists for this reason: it's a normal,
  low-risk account, shown so the analyst can see what normal looks like
  next to what isn't.
- Nobody in this workflow wants to see all 44 accounts as an undifferentiated
  mass. The default graph view (no pattern selected) is honestly less
  useful than the filtered view — this is fine and expected; the pattern
  list is the primary navigation, not a filter bolted onto a graph-first
  design.

## 2. Core user jobs

**Job 1 — "Is there a problem right now?"**
Smallest UI: four numbers (accounts, flagged, active patterns, flagged
volume) visible without any interaction. This has to be true on page load,
before any click, or the dashboard reads as empty rather than as "all
clear."

**Job 2 — "What kind of problem, and how many patterns are there?"**
Smallest UI: a list of pattern cards, one per detected pattern, each naming
its type (structuring / layering / round-tripping) and a one-line plain-
English summary. No graph interaction required to understand this — the
card alone should let the analyst decide whether to look further.

**Job 3 — "Show me exactly which accounts and how they connect."**
Smallest UI: clicking a pattern card filters the graph to that pattern's
accounts, laid out so the shape (hub, chain, loop) is visually obvious
without manual dragging. This is the centerpiece; everything else is
context for it.

**Job 4 — "Is this one account's activity actually suspicious over time,
or a one-off?"**
Smallest UI: clicking any account (in the graph or the table) shows a
30-day volume chart for just that account. A spike that lines up with the
pattern's detection date is the confirming signal.

**Job 5 — "Let me browse or sanity-check accounts outside the flagged
patterns."**
Smallest UI: a sortable-by-risk table of all accounts, so the analyst can
confirm the flagged ones actually stand out from the population, not just
from each other.

## 3. Layout derivation

Four regions, not three, because jobs 1 and 2 cannot share a region without
one of them losing priority — the KPI strip has to be visible with zero
interaction, so it can't live inside a scrollable column with the pattern
list.

```
┌────────────────────────────────────────────────────────────────┐
│  KPI strip (Job 1)                                    72px, fixed│
├───────────────┬──────────────────────────────┬──────────────────┤
│ Pattern list  │  Transaction graph            │  Timeline (38%)  │
│ (Job 2)       │  (Job 3)                      ├──────────────────┤
│ 260px         │  flex-1 (~660px)              │  Account table   │
│ own scroll    │  no page scroll, pans/zooms   │  (62%)           │
│               │  internally                   │  (Job 5)         │
│               │                                │  own scroll      │
└───────────────┴──────────────────────────────┴──────────────────┘
  Job 4 lives in the top of the right rail, fed by selection state
  shared between the graph and the account table.
```

At 1280px: 260 (patterns) + ~660 (graph) + 360 (right rail) = 1280, with
1px hairline borders absorbing the rounding. The right rail splits 38/62
between timeline and table by height, not by equal halves — the timeline
is a single chart that doesn't need much vertical room, and the table
benefits from showing more rows without scrolling.

Deviation from convention: most dashboards put the primary visualization
in the largest region and secondary lists in sidebars — that part is
conventional here too. The deviation is making the *left* sidebar the
primary navigation (pattern selection drives the graph) rather than a
set of filters or a nav menu. This follows directly from job 2 requiring
no graph interaction to be useful on its own — it's not a filter panel,
it's a findings list that happens to also filter.

What scrolls: pattern list (independently), account table (independently).
What doesn't scroll: the KPI strip, the graph region (it pans/zooms
internally via React Flow, page scroll would fight that), the timeline
chart (fixed height, no need).

## 4. Component decomposition

Thirteen components. Ownership boundaries below; if a component isn't
listed as owning something, assume it explicitly does not do it.

- **`App`** — owns `selectedPatternId` and `selectedAccountId` (the only
  two pieces of cross-component state in the app), and the four-region
  grid. Does not fetch data itself.
- **`KPIBar`** — owns fetching `/api/summary` and rendering the four
  stats. Does not know about pattern or account selection.
- **`PatternList`** — owns fetching `/api/patterns`, rendering cards, and
  toggling `selectedPatternId` (click again to deselect). Does not touch
  the graph directly — communicates purely through the lifted state.
- **`TransactionGraph`** — owns fetching `/api/graph` (parameterized by
  `selectedPatternId`), running dagre layout, capping nodes, styling
  edges by amount, and emitting `onSelectAccount` on node click. Does not
  own selection state, only reads and reports it.
- **`RiskNode`** — owns rendering a single node's visual (color by risk
  tier, flagged marker, label). Pure presentational, no data fetching, no
  awareness of the graph as a whole.
- **`layout.js`** (not a component) — owns the dagre call and the grid
  fallback. Explicitly does not know about React or rendering; it's a
  pure function of nodes/edges to positioned nodes.
- **`AccountTable`** — owns fetching `/api/accounts` and emitting
  `onSelectAccount` on row click. Does not filter by pattern — it always
  shows the full account population, by design (job 5).
- **`TimelineChart`** — owns fetching `/api/account/:id/timeline` when
  `accountId` is non-null, and rendering the Recharts area chart. Does not
  fetch anything when no account is selected — renders its empty state
  instead of calling the API with a null id.
- **`LoadingState` / `ErrorState` / `EmptyState`** — pure presentational,
  reused by every data-owning component above. Own nothing but their own
  message and (for `ErrorState`) a retry callback.
- **`useApiResource`** (not a component) — owns the loading/success/error
  status machine shared by every data hook. Does not know what it's
  fetching.
- **`useSummary` / `useAccounts` / `usePatterns` / `useGraph` /
  `useTimeline`** — each owns exactly one endpoint's fetch + dependency
  array. Does not transform response shapes — that's the API client's job
  if it's needed at all, and here it isn't (mock and live share a shape).

Loading/error/empty is implemented identically in all five data-owning
components: `status === 'loading'` → `LoadingState`, `status === 'error'`
→ `ErrorState` with retry, `status === 'success'` with an empty array/null
→ `EmptyState`, `status === 'success'` with data → the real render. This
repetition is intentional — five components are simple enough that a
shared "DataBoundary" wrapper would save a few lines and cost a layer of
indirection a teammate has to learn during a 24-hour build.

## 5. Graph visualization approach

**Node/edge shape.** React Flow nodes need `id`, `type`, `data`,
`position`. We send `type: "risk"` so our custom `RiskNode` renders instead
of the default box, and we always send `position: {x:0,y:0}` from the
backend because the frontend recomputes it. See `BACKEND_CONTRACT.md`
section 3 for the exact JSON.

**Dagre integration.** Dagre wants a `{nodes, edges}` graph with width/
height hints per node; it returns center-point positions per node id. We
convert those to React Flow's top-left `position` (subtracting half the
node's width/height) in `layout.js`. Direction is left-to-right (`rankdir:
'LR'`), which reads naturally for money "flowing" from left to right
sources into right-side destinations.

**The trap that renders the graph blank**, in order of how often it
actually happens:

1. **Zero-height parent.** React Flow measures its container on mount. A
   flex child with no explicit height defaults to `min-height: auto`,
   which collapses to the height of its content — and an empty React Flow
   canvas has no content, so it collapses to 0px and never grows. Fix:
   the wrapper around `<ReactFlow>` is `h-0 flex-1`, which forces a flex
   child to actually fill available space instead of sizing to content.
   This is the single most common React Flow support question online and
   it will happen on hour one if you skip it.
2. **Dangling edges.** An edge referencing a `source` or `target` id not
   present in the current `nodes` array (e.g. after the node cap removes a
   node) makes dagre throw, and an uncaught throw during render leaves
   the canvas blank with no visible error. Fix: `layout.js` filters out
   any edge whose endpoints aren't in the node set before calling dagre,
   and the whole layout call is wrapped in try/catch regardless.
3. **All nodes at the same position.** If dagre silently fails to place a
   node (rare, but happens with malformed graphs), that node's position is
   `undefined`, which React Flow renders as `(0,0)` — every unplaced node
   stacks exactly on top of each other and looks like one node or an
   empty canvas depending on zoom. Fix: `computeLayout` checks that every
   node got a finite `x`/`y` after dagre runs, and falls back to the grid
   layout for the whole graph if not — better a readable grid than a
   silent stack.

**Fallback if auto-layout misbehaves:** `layoutGrid` in `layout.js` places
nodes in a deterministic grid, no edges considered. It's uglier than a good
dagre layout but it is never blank and never overlapping, and it's what
ships if dagre throws for any reason. This is a real code path, not a
placeholder — `computeLayout` calls it automatically on dagre failure, so
nobody has to notice or intervene during the demo.

**Risk encoding:** node background/border color by tier — green
(`risk < 45`), amber (`45–74`), red (`≥ 75`) — plus a small flag glyph
for `flagged: true`. Color is redundant with the numeric risk score printed
on the node, which matters for anyone who can't rely on color alone.

**Edge readability at 20+ edges:** two edge classes, not a continuous
scale. Edges carrying ≥ $15,000 are drawn at 2px, full opacity, gold,
animated, and labeled with the dollar amount. Everything else is 1px,
55% opacity, muted gray, unlabeled. Without this split, a graph with the
tail-noise edges included (see mock data) turns into unreadable spaghetti
with 15 overlapping dollar labels. The two-class split is a five-minute
implementation that buys most of the readability a continuous
amount-to-width scale would, without the tuning time a continuous scale
needs to not look arbitrary.

**Node cap:** 60 nodes, hard-coded. Above that, `TransactionGraph` keeps
the 60 highest-`risk` nodes and drops the rest, along with any edge that
would dangle as a result. This is communicated with a visible banner —
"Showing top 60 of N accounts by risk score" — rather than silently
truncating, because a judge or analyst who counts nodes and gets a number
smaller than the KPI strip's `totalAccounts` will assume something is
broken if there's no explanation.

**Worked example — ACC_001, ACC_042, ACC_117, ACC_205:**

- `ACC_001` is the structuring hub. Selecting the structuring pattern
  filters the graph to `ACC_001` plus five sending accounts
  (`ACC_010`–`ACC_014`). Dagre with `rankdir: 'LR'` places the five
  senders in a left column and `ACC_001` alone on the right — visually a
  hub, because five edges converge on one node, without anyone having
  manually positioned anything.
- `ACC_042` anchors the layering chain: `ACC_042 → ACC_043 → ACC_044 →
  ACC_045`, each edge carrying a slightly smaller amount than the last
  ($152,000 → $141,500 → $133,800 → $126,200). Left-to-right layout draws
  this as a visibly diagonal chain, and because all four edges clear the
  $15,000 label threshold, all four dollar amounts are visible at once —
  the shrinking numbers left to right *are* the "layering" story, no
  further explanation needed on screen.
- `ACC_117` anchors the round-trip: `ACC_117 → ACC_118 → ACC_119 →
  ACC_117`. This is the one pattern dagre struggles with by default,
  because a cycle fights a strictly-ranked left-to-right layout — dagre
  will draw the return edge (`ACC_119 → ACC_117`) as a long curve back
  across the graph rather than a short loop. That's fine and expected:
  the return edge being visually distinct (crossing back over the other
  two) is itself legible as "this loops back," not a layout bug to fix
  under time pressure.
- `ACC_205` never appears in a pattern's member list. It shows up once, as
  a low-risk (`34`) account feeding a small amount into `ACC_010` (one of
  the structuring senders) — a legitimate-looking counterparty sitting one
  hop outside the flagged cluster. It's in the mock data specifically so
  the unfiltered graph view has at least one example of "adjacent but not
  itself flagged," which is what most real accounts near a laundering
  network actually look like.

## 6. API integration design

Per region:

- **KPI strip** — needs `/api/summary`. Fetched once, on mount, no
  dependency on other state. Slow fetch (> ~1.5s): loading spinner in the
  header, rest of the app unaffected. Failure: inline error with retry,
  scoped to the header only — a broken summary shouldn't take down the
  graph.
- **Pattern list** — needs `/api/patterns`. Fetched once, on mount.
  Failure/slow behavior same pattern as above, scoped to that column.
- **Transaction graph** — needs `/api/graph`, re-fetched whenever
  `selectedPatternId` changes (including changing to `null`, which
  refetches the full graph). This is a deliberate refetch-on-change
  policy, not a cache — patterns don't change fast enough in a 24-hour
  demo for caching to matter, and refetching keeps the mental model
  simple: one state variable, one source of truth, no stale-cache bugs to
  debug at hour 20.
- **Account table** — needs `/api/accounts`. Fetched once, on mount. Does
  not refetch on pattern selection (by design — job 5 is about the whole
  population, not the filtered one).
- **Timeline chart** — needs `/api/account/:id/timeline`, fetched only
  when `selectedAccountId` is non-null, refetched whenever it changes.
  No fetch at all (not even a disabled one) when nothing is selected —
  the hook returns a resolved `null` locally rather than hitting the
  network, which also means there's no error state to handle for "no
  account selected."

**API client structure:** one file, `src/api/client.js`, exporting a
single `api` object with one method per endpoint. Every method: (1) checks
`VITE_USE_MOCK` and either delays-then-returns mock data or calls axios,
(2) normalizes both mock and axios errors into `{ message, status }` so
every component's `ErrorState` reads the same shape regardless of mode.
No component imports axios or the mock module directly — that's the whole
point of the layer. Adding a sixth endpoint later means adding one method
here and one hook in `src/hooks/`, touching zero existing components.

## 7. File structure

Load-bearing (the app doesn't run or the graph blanks out without these):

- `src/main.jsx` — React root, load-bearing
- `src/App.jsx` — layout shell and shared selection state, load-bearing
- `src/api/client.js` — the one API layer, load-bearing
- `src/mock/mockData.js` — mock data generator, load-bearing for demo mode
- `src/hooks/useApiResource.js` — shared fetch/status machine, load-bearing
- `src/hooks/useSummary.js` — load-bearing
- `src/hooks/useAccounts.js` — load-bearing
- `src/hooks/usePatterns.js` — load-bearing
- `src/hooks/useGraph.js` — load-bearing
- `src/hooks/useTimeline.js` — load-bearing
- `src/components/kpi/KPIBar.jsx` — load-bearing
- `src/components/patterns/PatternList.jsx` — load-bearing
- `src/components/graph/TransactionGraph.jsx` — load-bearing, the
  centerpiece
- `src/components/graph/RiskNode.jsx` — load-bearing (custom node type)
- `src/components/graph/layout.js` — load-bearing (dagre + fallback)
- `src/components/accounts/AccountTable.jsx` — load-bearing
- `src/components/timeline/TimelineChart.jsx` — load-bearing
- `src/components/common/LoadingState.jsx` — load-bearing (used everywhere)
- `src/components/common/ErrorState.jsx` — load-bearing
- `src/components/common/EmptyState.jsx` — load-bearing
- `src/index.css` — load-bearing (Tailwind layers + React Flow theme
  overrides)
- `index.html` — load-bearing
- `vite.config.js`, `tailwind.config.js`, `postcss.config.js` — load-bearing
  build config
- `package.json` — load-bearing

Hygiene (make the project usable/deployable but nothing on screen depends
on them):

- `README.md`
- `BACKEND_CONTRACT.md`
- `GUIDE.md`
- `.env.example`
- `.gitignore`

## 8. 24-hour build sequence

**Hours 0–2: scaffold and contract.** Set up Vite + Tailwind + the file
structure above. Write `BACKEND_CONTRACT.md` and mock data *before*
writing components — the mock data is the spec your teammate builds
against, and writing it first forces you to decide every field name once.
End-of-phase state: `npm run dev` shows a blank styled page. Sync point:
send the backend teammate `BACKEND_CONTRACT.md` now, not later — they need
the full 24 hours against a fixed target, not whatever's left after you
finish the frontend. Do not start on the graph yet.

**Hours 2–6: static layout with mock data.** Build all five regions
against mock data, no interactivity between them yet (graph doesn't filter
on pattern click, table doesn't drive the timeline). End-of-phase state:
all four API-shaped regions render real-looking mock data at 1280px, loading
states visible on refresh (throttle network in devtools to confirm).
Definition of done: every region shows loading → data with no layout
jump. Do not polish colors or spacing yet.

**Hours 6–10: React Flow and dagre.** This is the highest-risk block —
budget it generously and start it early, not late. Get one hardcoded
5-node graph rendering with dagre layout before touching the real mock
data. End-of-phase state: `TransactionGraph` renders the full mock graph,
color-coded, with working pan/zoom. Definition of done: the three named
patterns (structuring/layering/round-trip) each visibly look like their
name when selected. Do not implement the node cap or edge-amount
thresholds yet if you're behind — a graph that's slightly too busy still
demos; a graph that doesn't render doesn't.

**Hours 10–14: interactivity and cross-component state.** Wire pattern
selection → graph refetch, node/row click → timeline. End-of-phase state:
clicking through all three patterns and a few accounts tells a coherent
story with no dead clicks. Sync point: ask the backend teammate for a
live endpoint or two now, even incomplete — flip `VITE_USE_MOCK=false`
against whatever's up and fix integration surprises (CORS is the usual
one) while there's still runway. Definition of done: at least one real
endpoint renders correctly end to end.

**Hours 14–18: full backend integration.** Swap mock for live across all
five endpoints as the backend teammate finishes them. End-of-phase state:
`VITE_USE_MOCK=false` works for the whole dashboard against the real
Railway deployment. Do not chase mock-data edge cases (e.g. the exact
noise-edge count) once live data exists — mock mode's job is done once
this phase starts; polish is aimed at real data behavior now.

**Hours 18–21: node cap, edge thresholds, empty/error polish, node cap
banner, and the fallback grid layout.** These are the details that were
explicitly deferred in hours 6–10. End-of-phase state: every failure mode
in section 9 has been manually triggered once (kill the backend, request
a huge account set, request an unknown pattern id) and degrades
gracefully. Definition of done: nothing in the app shows a blank white
screen or an uncaught error under any of those conditions.

**Hours 21–23: Vercel deploy and demo rehearsal.** Deploy early enough to
fix env var or build issues with time to spare — see risk 5 in section 9.
Run the demo script (section 10) twice, out loud, on the deployed URL, not
localhost. Definition of done: the demo script runs start to finish on the
deployed build without a laptop-only fix in your head.

**Hour 23–24: buffer.** Reserved for whatever section 9 actually
triggered. Do not schedule real work here.

**Cut if behind schedule, in this order:** the MiniMap (nice, not load-
bearing), the animated/gold treatment on heavy edges (a static thicker
line communicates the same thing), the account table's flagged-account
sort emphasis beyond plain risk-score sort, any second color pass on the
KPI strip. Do not cut: the node cap banner, the dagre-failure fallback, or
any loading/error state — those are the difference between "rough" and
"broken" in front of judges.

## 9. Top frontend risks

- **Risk: React Flow renders blank.**
  Warning sign: canvas area is empty but no console error.
  Fallback: check the container height chain first (section 5, trap 1) —
  this is the cause 9 times out of 10. `h-0 flex-1` on the direct
  `<ReactFlow>` wrapper is already in place; if it's still blank, check
  for a dangling edge in whatever data is currently loaded.
  Trigger hour: if it's not resolved by hour 8, stop other graph work and
  fix this first — nothing else in `TransactionGraph` can be verified
  visually until it renders at all.

- **Risk: layout chaos (nodes overlapping or off-canvas).**
  Warning sign: dagre runs without throwing but the result looks wrong —
  usually a disconnected component (a node with no edges) placed on top of
  another node.
  Fallback: `layoutGrid` in `layout.js` is already wired as the automatic
  fallback on dagre failure; if dagre succeeds but looks bad rather than
  throwing, manually widen `nodesep`/`ranksep` in `layout.js` before
  reaching for the grid fallback — those two numbers fix most real dagre
  layout complaints.
  Trigger hour: by hour 10, if the three named patterns don't each look
  visually distinct from each other, stop and fix `nodesep`/`ranksep`
  rather than proceeding to interactivity work on a graph that doesn't
  read.

- **Risk: CORS blocks every real API call.**
  Warning sign: every live-mode request fails with a network error that
  has no response body, and the browser console shows a CORS error even
  though the endpoint works fine in curl/Postman.
  Fallback: confirm the backend sends
  `Access-Control-Allow-Origin` for both `http://localhost:5173` and the
  Vercel domain; this is a backend-side fix, not a frontend one — don't
  try to work around it with a frontend proxy under time pressure.
  Trigger hour: check this at the hour-10 sync point (section 8), not the
  first time you flip `VITE_USE_MOCK=false` at hour 18 with no time left
  to loop back to the backend teammate.

- **Risk: slow endpoints freeze the UI.**
  Warning sign: clicking a pattern or account makes the whole app feel
  unresponsive, not just the region that's loading.
  Fallback: every fetch already goes through `useApiResource`, which sets
  `status: 'loading'` for that region only — if something still feels
  frozen, check for a fetch that bypassed the hook (a stray `useEffect`
  calling `api.*` directly), not a hook bug.
  Trigger hour: if any interaction takes longer to feel done than the
  8-second axios timeout, treat it as broken, not slow — 8 seconds is
  already generous for a demo click.

- **Risk: Vercel deploy fails late.**
  Warning sign: build succeeds locally but fails on Vercel, usually an env
  var typo (`VITE_` prefix missing) or a case-sensitivity issue in an
  import path that only surfaces on Linux CI.
  Fallback: deploy a throwaway commit to Vercel during hours 2–6, before
  there's anything worth losing, specifically to catch this class of
  problem while it's cheap to fix.
  Trigger hour: if you haven't deployed successfully at least once by
  hour 14, that's the fallback triggering late — stop other work and
  deploy immediately, even a half-finished build.

- **Risk: over-polishing one element.**
  Warning sign: spending more than an hour on any single visual detail —
  the risk-color gradient, the MiniMap styling, the pattern card hover
  state — while another region still shows raw mock data or a missing
  empty state.
  Fallback: the cut list at the end of section 8 exists for exactly this;
  if you notice you're past an hour on a decorative detail, stop and check
  whether every region has its loading/error/empty states before
  continuing.
  Trigger hour: any time, but especially hours 18–21, which are explicitly
  budgeted for functional polish (states, cap, fallback) — protect that
  time from cosmetic tinkering.

## 10. Demo script (3 minutes)

1. Open the deployed URL. The KPI strip is already showing 44 accounts, 13
   flagged, 3 active patterns — "the system found three laundering
   patterns in this account population without anyone telling it what to
   look for."
2. Click the structuring pattern card. The graph redraws to five accounts
   converging on one. "Five different accounts each sent just under the
   $10,000 reporting threshold, all landing in the same account within 36
   hours — structuring, by definition."
3. Click the hub node (`ACC_001`). The right rail's timeline updates.
   "Here's that account's actual volume — it's flat for weeks, then this."
4. Click back to the pattern list, select the layering pattern. "Same
   idea, different shape — money moving through a chain, losing a little
   value at each hop on purpose, so the trail gets harder to follow."
5. Select the round-tripping pattern. "And this one is money that just...
   comes back. Three hops, same account it started from."
6. Click deselect (click the selected pattern again) to show the full
   graph. "Zoomed out, this is every account — the three clusters we just
   walked through are the specific shapes buried in this noise, and that's
   what the system is actually finding: not a rule, a shape."
7. End on the graph, not the table — the last thing on screen should be
   the network, because that's the thing a transaction-list tool couldn't
   have shown.

## 11. Frontend resume line

Built a real-time transaction-network visualization (React, React Flow,
dagre auto-layout) that renders 40+ account graphs with risk-based
encoding and a custom node-cap/fallback-layout system to keep the UI
legible and crash-free under malformed or oversized graph data.

---

## Build and verify

Zip everything in this project's root (including `src/`, the config files,
`README.md`, `BACKEND_CONTRACT.md`, and this file) — exclude `node_modules`
and `dist`. Before the demo: run `npm install && npm run dev` from a clean
clone of the zip's contents, confirm all three named patterns render
distinct shapes in the graph, confirm switching `VITE_USE_MOCK` to `false`
against the live backend doesn't change any component code, and run
`npm run build` once to catch anything that only breaks in production
mode.
