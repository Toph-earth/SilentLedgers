// The live backend sends risk on two different scales depending on the
// endpoint: /api/accounts and /api/patterns use an integer 0-100
// `riskScore`, but /api/graph node data uses a float 0-1 `risk`
// (see API_REFERENCE.md — data: { label, risk: 0.94 }). Every place in the
// UI that colors or thresholds by risk goes through this file so the two
// scales never have to be reconciled twice.

export function normalizeRisk(risk) {
  if (risk == null || Number.isNaN(risk)) return 0;
  return risk <= 1 ? Math.round(risk * 100) : Math.round(risk);
}

export function riskTier(risk) {
  const r = normalizeRisk(risk);
  if (r >= 75) return 'high';
  if (r >= 45) return 'mid';
  return 'low';
}

export function riskColorClass(risk) {
  const tier = riskTier(risk);
  if (tier === 'high') return 'text-risk-high';
  if (tier === 'mid') return 'text-risk-mid';
  return 'text-risk-low';
}

// Matches the backend's own flagged rule (riskScore >= 60) so a graph
// node's flag glyph agrees with the account table even on payloads (like
// /api/graph) that don't include an explicit `flagged` field.
export function isFlagged(risk) {
  return normalizeRisk(risk) >= 60;
}
