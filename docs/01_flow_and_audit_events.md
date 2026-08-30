# AS-IS / TO-BE Flow and Audit Event Catalogue

## AS-IS Process

1. Analyst reads fund guidelines manually.

2. Analyst copies limits into a spreadsheet.

3. Analyst pulls holdings snapshot manually.

4. Analyst computes allocations, concentrations, liquidity, duration, DV01 manually.

5. Analyst fills report template by hand.

6. Audit trail is weak: formulas are buried in spreadsheet tabs.

Pain points:

- slow,
- error-prone,
- hard to defend in audit,
- no reliable figure-to-source traceability.

## TO-BE Process

1. Ingest guidelines into a deterministic rule/graph seed.
2. Human review gate validates extracted graph entities and relationships.
3. Ingest holdings snapshot into the same knowledge graph.
4. Deterministic computation engine traverses the graph to compute every figure.
5. Reconciliation engine compares output to answer key.
6. Traceability checker verifies figure → graph path → source.
7. Narrative layer may generate commentary only, never numbers.
8. Firewall checker verifies narrative contains no unauthorized numbers.
9. Export report and append all events to append-only audit log.

## Human Gates

### Gate 1: Graph Extraction Review

- Purpose: verify entities and relationships extracted from guidelines.

- Auto-pass criterion:
  - all entities resolved,
  - extraction_confidence >= 0.95,
  - no missing limits or unmatched asset classes.

- Else: human review required.

### Gate 2: Configuration Change Review

- Purpose: approve firm method configuration changes.
- Auto-pass criterion:
  - config schema valid,
  - only whitelisted method fields changed.
- Else: compliance sign-off required.


### Gate 3: Reconciliation Review

- Purpose: verify computed figures match answer key or approved tolerance.
- Auto-pass criterion:
  - all required fields pass,
  - numeric delta = 0 or within documented tolerance.
- Else: human investigation required.

### Gate 4: Narrative Firewall Review

- Purpose: ensure narrative introduces no new numbers.
- Auto-pass criterion:
  - every number in narrative exists in computed figure set.
- Else: block release.

### Gate 5: Final Report Release

- Purpose: formal approval before distribution.
- Auto-pass criterion:
  - none. This is always human-approved.

## Audit Event Catalogue

| Event | Trigger | Data Captured | Retention |
|---|---|---|---|
| CONFIG_LOADED | Run starts with a firm config | config path, config hash, firm id | 7 years |
| FALLBACK_INPUT_USED | Primary input missing | original path, fallback path | 7 years |
| GRAPH_CONSTRUCTED | Knowledge graph built | node count, edge count, graph hash | 7 years |
| UNRESOLVED_ENTITY | Entity cannot be resolved | entity id, reason, row | 7 years |
| FIGURES_COMPUTED | All figures computed | figure count, figures hash | 7 years |
| REPORT_EXPORTED | XLSX written | report path | 7 years |
| RECONCILIATION_COMPLETED | Reconciliation finished | overall pass/fail | 7 years |
| TRACEABILITY_CHECK | Traceability validation finished | pass/fail, issue count | 7 years |
| NARRATIVE_FIREWALL | Narrative firewall finished | pass/fail, invalid numbers | 7 years |

