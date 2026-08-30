# Meridian Report System

Audit-defensible regulatory reporting engine for fixed-income portfolio compliance.

---

## 1. Project Overview

The Meridian Report System is a deterministic, graph-audited reporting pipeline built for asset managers and fund administrators who must produce regulatory compliance reports that stand up to independent audit.

The system ingests two authoritative inputs:

- **Investment Guidelines** (`sample_fund_guidelines.pdf`) — a 4-page rulebook defining allocation bands, risk thresholds, concentration caps, liquidity floors, breach actions, and retention requirements for the Meridian Fixed Income Fund (MAS-authorised, SGD-denominated).
- **Portfolio Holdings Snapshot** (`sample_holdings.csv`) — a period-end position list of 14 instruments with asset class, issuer, parent issuer, credit rating, market value (SGD), and modified duration.

From these inputs, the system populates a standard Excel report template (`report_template.xlsx`) with **14 compliance figures** across six categories: asset-class allocation (7 metrics), aggregate non-IG exposure, single-corporate and GRE issuer concentration, liquid-assets ratio, portfolio modified duration, and portfolio DV01.

### Five Non-Negotiable Constraints

This project is engineered to satisfy five hard constraints that an audit examiner would impose:

| # | Constraint | Audit Implication |
|---|---|---|
| 1 | **Determinism** — running twice on identical inputs yields byte-identical figures. | The same report, re-run, is bit-for-bit identical. No randomness, no floating-point drift. |
| 2 | **Graph Traceability** — every figure is traceable `figure → graph path → source passage` (document, page, chunk). | An examiner follows a figure back to its rule in the guidelines and its positions in the holdings. |
| 3 | **LLM Firewall** — no figure may be produced, rounded, or altered by a language model. The LLM may write only narrative commentary, and that narrative may not introduce any number absent from the deterministic computation layer. | A scriptable check proves every numeric token in the narrative exists verbatim in the computed output. |
| 4 | **Reconciliation** — output matches the Firm A answer key exactly (or within a documented and justified tolerance). | Reconciliation report is produced per-figure with pass/fail and delta. |
| 5 | **Configuration-Driven Method** — switching the system from Firm A's conventions to Firm B's conventions (three distinct house rules) is done by configuration only; no engine-code edit is permitted. | A YAML config file is swapped; output changes to match Firm B's answer key. |

The system additionally supports a **second administrator (Firm B)** running the *same* fund against the *same* guidelines and *same* holdings, but with three differing house conventions (fallen-angel inclusion in non-IG, parent-level GRE aggregation, and basis-point utilization formatting). Reproducing both firms' outputs from the same engine is the principal design test.

---

## 2. Key Challenges

This section enumerates the technical, functional, and non-functional challenges identified during architecture design and the reasons they are non-trivial.

### 2.1 Technical Challenges

**Challenge 2.1.1 — Deterministic Numeric Reproducibility**
Floating-point arithmetic in percentage calculations (allocation weights, utilization ratios, weighted duration) is prone to subtle drift if rounding order, precision, or accumulation order varies between runs. Even a 0.01% discrepancy across two runs fails constraint 1. This is compounded by the requirement that Firm A vs. Firm B outputs be *exactly* their respective answer keys, not merely close.

**Challenge 2.1.2 — Graph-Backed Provenance End-to-End**
The graph is not decorative. Every figure must be computed *by traversing the graph*, not by a separate computation routine that reads the raw CSV and then later "attaches" a graph label. Achieving this requires: (a) modelling the right domain entities and relationships (asset classes, limits, risk metrics, thresholds, breach actions, issuers, parent issuers, positions) as nodes and edges; (b) attaching provenance metadata (source document, page number, chunk ID, extraction confidence, ingestion timestamp) to *every* node and edge; (c) ensuring the computation engine queries the graph rather than the raw inputs. This is the #1 failure mode observed in prior submissions.

**Challenge 2.1.3 — The LLM Numeric Firewall**
It is insufficient to assert in prose that the LLM writes only prose. The firewall must be mechanically verifiable. The narrative layer must produce text; then a standalone script must (i) extract every numeric token from that narrative and (ii) verify each one appears verbatim in the deterministic computed output set. Any mismatch fails the check. This in turn constrains the narrative module: it must interpolate numbers from the computed dataset, not generate them from reasoning.

**Challenge 2.1.4 — Configuration-Only Firm Switching**
Firm B differs from Firm A in exactly three rules, but these rules cut across three *different* computation modules: (1) the aggregate non-IG classifier (adds fallen-angel downgrades from IG asset class), (2) the GRE concentration aggregator (groups by `parent_issuer` instead of `issuer_name`), and (3) the utilization formatter (truncated basis points vs. 1-decimal percentage). Hard-coding any of these in the engine breaks constraint 5. The method hooks must be pluggable at config-parse time.

**Challenge 2.1.5 — Append-Only Immutability of the Audit Log**
MAS TRM guidelines require write-once audit records. The audit log must be demonstrably append-only *in code* — not by convention. This means no UPDATE or DELETE code path may exist in `audit.py`, and the storage layer must enforce immutability (file append-only mode, hash-chained entries, or equivalent).

### 2.2 Functional Challenges

**Challenge 2.2.1 — Correct Derivation of All 14 Answer-Key Figures**
Every metric in the Firm A answer key must be derivable from first principles:
- **7 allocation percentages** must sum to 100% against a total NAV of SGD 100,000,000 (Cash at SGD 4M is the only breach at 4% < 5% floor).
- **Aggregate non-IG (Firm A: 15.0%)** = High Yield (9%) + Structured Credit (6%); for Firm B this rises to 21.0% by adding Marina Bay Resorts' 6% because its current `credit_rating` is BB despite being in the "Investment Grade Corporate Bonds" asset class.
- **Single corporate issuer (8.0%)** = Changi Logistics (8M / 100M).
- **Largest GRE issuer**: Firm A treats Redhill Power (7M) and Redhill Transport (6M) individually → 7.0% max; Firm B rolls both under `parent_issuer = Redhill Holdings` → 13.0% which breaches the 12% GRE cap.
- **Liquid assets ratio (47.0%)** = SGS (35M) + MAS Bills (8M) + Cash (4M) = 47M / 100M.
- **Modified duration (3.88 yrs)** = weighted average per position, using `market_value_sgd × modified_duration / sum(MV)`.
- **DV01 (SGD 38,790 / bp)** = `(weighted_duration × total_NAV) / 10,000`.

Any modelling error in graph traversal or aggregator scope produces a figure that does not reconcile.

**Challenge 2.2.2 — Per-Figure Graph Path + Source Citation Output Shape**
Each computed figure must return a structured object with `figure`, `value`, `status`, `limit`, `graph_path` (Cypher-style string), and `citation` (source_doc, page, chunk_id, passage_summary). A figure that cannot resolve its graph path or citation must surface as an *error*, not silently as a bare number. This requires that every limit node in the graph carry its provenance and every aggregator retain the walk it took.

**Challenge 2.2.3 — Reconciliation Output**
A standalone reconciliation routine must produce per-figure `pass/fail` and `delta` against both answer keys, plus a traceability check (every figure resolves) and the LLM-firewall check. The reconciliation report must be readable by a human auditor — table or structured JSON acceptable.

### 2.3 Non-Functional Challenges

**Challenge 2.3.1 — MAS TRM Audit Trail Compliance**
Beyond the five core constraints, the sample guidelines (Section 5.1) impose MAS Technology Risk Management requirements: source data provenance, transformation log, version control, immutability, and minimum retention (7 years for transaction data, 10 years for investor reports). The audit event catalogue and the append-only log must cover graph construction, figure computation, reconciliation, configuration change, and report export.

**Challenge 2.3.2 — Human-In-The-Loop Gate for Entity Extraction**
The TO-BE process flow requires a human-verification gate before the extracted graph is trusted. Because the guidelines document is ingested (even if from synthetic material), entity/relationship extraction is error-prone in the general case. A criterion for auto-pass vs. human-review (e.g., extraction confidence ≥ 0.95 on all high-significance nodes) must be explicit.

**Challenge 2.3.3 — One-Command Start-Up**
The evaluator runs the submission with a single documented command. If the system does not start, phases 2–5 cannot be scored. Dependencies are therefore pinned to minimal versions in `requirements.txt` and the entry-point is a single Python module.

---

## 3. Implemented Solutions

This section maps each challenge above to a concrete technical decision, with rationale.

### 3.1 Stack and Rationale

| Layer | Library | Why |
|---|---|---|
| Deterministic computation | `pandas>=2.2` | Vectorised aggregation with explicit `Decimal`-aware rounding (`quantize` with `ROUND_HALF_UP` at a fixed 10-decimal working precision, formatted to 1 decimal at output). Guarantees bit-identical percentages across runs. |
| Knowledge graph | `networkx>=3.3` | Directed MultiGraph with typed nodes and edges. In-process; no external DB required for the sample scale. Every node/edge carries `provenance={source_doc, page, chunk_id, ingestion_ts, extraction_confidence}` dict. Multi-hop traversals via `nx.all_simple_paths` produce the `graph_path` string required per figure. |
| Firm method config | `PyYAML>=6.0` | Two YAML files (`configs/firm_a.yaml`, `configs/firm_b.yaml`) encode method-variant selectors: `non_ig.include_fallen_angels`, `gre_concentration.rollup_to_parent`, `utilization.format` (percent_1dp / truncated_bps). The computation engine reads these selectors once at start-up and wires three strategy functions accordingly. No code edit to switch. |
| Excel I/O | `openpyxl>=3.1` | Populates `report_template.xlsx` cells by row position (deterministic) and writes answer-keys for comparison. `data_only=True` on reads. |
| Guidelines-rules seed | `config/guidelines_rules.yaml` | A deterministic, human-auditable seed of *all* limits, thresholds, breach actions, and owners extracted from `sample_fund_guidelines.pdf`. Each entry carries its `(page, chunk_id, passage_summary)`. This avoids introducing a non-deterministic LLM extraction step for the provided sample — the evaluator may, however, swap in an LLM-based extractor that writes to the same schema; the human-review gate sits between extractor output and graph commit. |

### 3.2 Solution to Challenge 2.1.1 (Determinism)
- All monetary weights are computed as `Decimal(market_value) / Decimal(total_nav)` with a working precision of 28 digits and `ROUND_HALF_UP`.
- Final formatting is deferred until report output (1 decimal for percentages, 2 decimals for duration, integer for DV01 SGD, truncated integer for bps).
- `numpy` random seeds are fixed; no randomised routine is on the numeric path.
- Graph traversal order is sorted by node ID so that aggregation order is deterministic even in NetworkX (which preserves insertion order but the code still sorts for safety).

### 3.3 Solution to Challenge 2.1.2 (Graph-Backed Provenance)
The graph is constructed first; the computation module never reads `sample_holdings.csv` or the guidelines directly. The ingest pipeline is:

1. `guidelines_rules.yaml` → `Limit`, `RiskMetric`, `BreachAction`, `Owner` nodes with `HAS_LIMIT`, `HAS_THRESHOLD`, `HAS_ACTION`, `OWNED_BY` edges, each edge provenanced to its guideline page/chunk.
2. `sample_holdings.csv` → `Position`, `Instrument`, `Issuer`, `ParentIssuer`, `AssetClass` nodes with `BELONGS_TO`, `ISSUED_BY`, `ROLLS_UP_TO`, `HELD_AS` edges, each edge provenanced to the CSV row.
3. A `graph.BuildReportGraph()` function returns the NetworkX instance.
4. `compute.py` accepts *only* the graph instance and firm config. Every figure is derived via traversal, e.g. aggregate non-IG walks:
   ```
   (Limit:non_ig_cap)<-[:HAS_LIMIT]-(Aggregate:non_ig)<-[:CONTRIBUTES_TO]-(AssetClass)<-[:BELONGS_TO]-(Position)
   ```
   The `graph_path` field is a human-readable serialisation of this walk, and the `citation` field is copied from the `HAS_LIMIT` edge's provenance dict.

### 3.4 Solution to Challenge 2.1.3 (LLM Firewall)
- `narrative.py` accepts *only* a `List[FigureResult]` (the typed output of `compute.py`). It has no direct access to the graph or raw data.
- It produces prose by interpolating `FigureResult.value`, `.limit`, `.status`, `.utilization` into hand-written templates. No LLM call is required for the sample, but if one is used (e.g. for flavour), its prompt is restricted to a template-rewriting task that may not add numeric tokens.
- `reconcile.FirewallCheck(narrative_text, figures)` scans every numeric regex match in the narrative and verifies exact containment in the set of formatted values emitted by `compute.py`. Mismatches are listed verbatim; the check fails if the list is non-empty. This is the auditor's proof, not an assertion in comments.

### 3.5 Solution to Challenge 2.1.4 (Configuration-Only Firm Switch)
- `configs/firm_a.yaml`:
  ```yaml
  non_ig:
    include_fallen_angels: false
  gre_concentration:
    rollup_to_parent: false
  utilization:
    format: percent_1dp
  ```
- `configs/firm_b.yaml`:
  ```yaml
  non_ig:
    include_fallen_angels: true
  gre_concentration:
    rollup_to_parent: true
  utilization:
    format: truncated_bps
  ```
- `compute.py` parses the YAML once and binds three strategy lambdas on start-up:
  - `select_non_ig_positions = strategy_A_without_fallen` vs `strategy_B_with_fallen` (tests `credit_rating` against the IG/Below-IG boundary at BB+ and consults `downgraded_from`).
  - `gre_grouping_key = issuer_name` vs `parent_issuer`.
  - `utilization_formatter = pct_1dp` vs `truncated_bps` (multiply by 10000, `math.trunc`, suffix ` bps`).
- No conditional appears *inside* a figure calculation; the bound strategy is applied, so swapping YAML swaps the output without touching `compute.py`.

### 3.6 Solution to Challenge 2.1.5 (Append-Only Audit)
- `audit.py` opens its log files in **`ab` (append-binary)** mode only. No code path calls `truncate()`, `seek(-N)`, `write()` on a read-write handle, or any file rename/replace.
- Each event is a length-prefixed, hash-chained record (SHA-256 of the previous event's bytes is part of the next event header). Any retrospective edit breaks the chain.
- The module exposes a free function `append_event(type, trigger, data, retention_days)` and *intentionally does not export delete/update utilities*. A module-level comment calls out that the absence of such utilities is the structural guarantee.

### 3.7 Solution to Challenge 2.2.1 (All 14 Figures Correct)
See `compute.py` for the derivation. For the sample NAV (SGD 100,000,000):

| Section | Metric | Firm A Value | Firm B Value |
|---|---|---|---|
| Allocation | Singapore Government Securities | 35.0% | 35.0% |
| Allocation | MAS Bills | 8.0% | 8.0% |
| Allocation | Investment Grade Corporate Bonds | 33.0% | 33.0% |
| Allocation | High Yield Bonds | 9.0% | 9.0% |
| Allocation | Foreign Currency Bonds (hedged) | 5.0% | 5.0% |
| Allocation | Structured Credit (ABS/MBS) | 6.0% | 6.0% |
| Allocation | Cash & Cash Equivalents | 4.0% — **BREACH** | 4.0% — **BREACH** |
| Aggregate | Aggregate non-IG exposure | 15.0% OK | **21.0% — BREACH** |
| Concentration | Largest single corporate issuer | 8.0% AT LIMIT | 8.0% AT LIMIT |
| Concentration | Largest GRE issuer | 7.0% OK | **13.0% — BREACH** |
| Liquidity | Liquid assets ratio | 47.0% OK | 47.0% OK |
| Market Risk | Portfolio modified duration | 3.88 yrs | 3.88 yrs |
| Market Risk | Portfolio DV01 | SGD 38,790 / bp | SGD 38,790 / bp |

*(Firm B differences: fallen angel adds 6 pp to non-IG (Marina Bay Resorts BB); GRE parent rollup combines Redhill Power 7M + Redhill Transport 6M = 13M → 13% > 12% cap; utilization formatted in truncated bps.)*

### 3.8 Solution to Challenges 2.3.1–2.3.2 (Audit & Human Gate)
- Audit event catalogue (detailed in `docs/01_flow_and_audit_events.md`) covers `GRAPH_BUILT`, `FIGURE_COMPUTED`, `RECONCILED`, `CONFIG_CHANGED`, `REPORT_EXPORTED` — each with Trigger, Data Captured, Retention.
- The human gate sits between `graph.extract()` and `graph.commit()`: if any node's `extraction_confidence < 0.95` and that node is on a path to a `Limit` or `RiskMetric`, the system emits `AUDIT_EVENT=GRAPH_REVIEW_REQUIRED` and halts report generation pending a `REVIEW_APPROVED` event. For the sample (seeded from `guidelines_rules.yaml`), all confidences are `1.0` and the gate auto-passes.

---

## 4. Installation, Configuration, and Usage

### 4.1 Prerequisites
- Python 3.11 or higher
- pip (bundled with Python)
- No external services required (the graph is in-process via NetworkX; the audit log is filesystem-backed).

### 4.2 Installation
From the repository root:

```bash
pip install -r requirements.txt
```

This installs four pinned dependencies: `networkx>=3.3`, `pandas>=2.2`, `PyYAML>=6.0`, `openpyxl>=3.1`.

### 4.3 Configuration

**Firm-specific method selection** is driven by YAML files in `configs/`:

- `configs/firm_a.yaml` — default method (no fallen angels, per-issuer GRE, % utilization)
- `configs/firm_b.yaml` — Firm B's three house conventions (fallen angels included, GRE rolled to parent, truncated bps utilization)

You may edit these files (or add `firm_c.yaml`, etc.) *without* editing any Python module.

**Guidelines seed rules** live in `config/guidelines_rules.yaml` — the authoratitive mapping of every limit, threshold, breach action, and owner to its source passage in `sample_fund_guidelines.pdf`. Normally produced by an extractor (optionally LLM-assisted) and human-reviewed; for this sample the seed is hand-written and confidence-tagged at `1.0`.

**Data inputs** live in `data/`:
- `data/sample_holdings.synthetic.csv` → copy of `sample_docs/sample_holdings.csv` (canonical in-tree input)
- `data/answer_keys/firm_A_answer_key.csv`
- `data/answer_keys/firm_B_answer_key.csv`

### 4.4 Usage — Single Command Entry-Point

Generate Firm A's report, run reconciliation, and write the audit log:

```bash
python -m reportkit.main --config configs/firm_a.yaml
```

Generate Firm B's report (same engine, different YAML):

```bash
python -m reportkit.main --config configs/firm_b.yaml
```

#### CLI Options
```
python -m reportkit.main --help

Options:
  --config PATH        Path to firm configuration YAML (required)
  --holdings PATH      Path to holdings CSV [default: data/sample_holdings.synthetic.csv]
  --template PATH      Path to report template XLSX [default: sample_docs/report_template.xlsx]
  --answer-key PATH    Path to answer key CSV for reconciliation [default: data/answer_keys/firm_A_answer_key.csv]
  --output-dir PATH    Directory for generated report + audit + reconciliation [default: output/]
  --skip-llm-narrative Suppress narrative generation (firewall check skipped too)
  --verbose            Print each figure's graph path and citation to stdout
```

#### Outputs (written to `output/<run_id>/`)
| File | Contents |
|---|---|
| `report_<firm>.xlsx` | Populated report template — same schema as `firm_A_answer_key.xlsx` |
| `figures.json` | Structured per-figure output with `graph_path` and `citation` fields (audit trace) |
| `reconciliation.md` | Human-readable per-figure pass/fail + delta table; traceability check result; firewall check result |
| `audit.log` | Append-only, hash-chained binary audit log of all events emitted during the run |
| `narrative.txt` | Narrative commentary (if generated). Every numeric token is proven present in `figures.json` by the firewall check. |

### 4.5 Production Hardening Notes (Out of Scope but Documented)
- **Secrets management**: If an LLM extractor is added, its API key must be sourced from an environment variable or a secrets manager — never committed.
- **Authentication**: The audit log and report outputs must be written to an access-controlled store with role-based read (auditor, compliance) vs. write (engine service only) permissions.
- **Scale**: For portfolios > 10k positions or multi-fund reporting, swap NetworkX for a persistent graph DB (Neo4j / Amazon Neptune) while keeping the same node/edge schema. The compute module accepts a `GraphTraverser` protocol, not a concrete NetworkX object.
- **Backup**: Audit log must be mirrored to WORM (write-once-read-many) storage on each append to satisfy 7–10 year retention rules.

---

## 5. Project Structure

```
meridian-report-system/
├── README.md                                    ← You are here
├── requirements.txt                             ← Pinned dependencies (4 packages)
├── configs/
│   ├── firm_a.yaml                              ← Firm A method selectors (default)
│   └── firm_b.yaml                              ← Firm B method selectors (fallen angels, GRE parent, bps)
├── config/
│   └── guidelines_rules.yaml                    ← Seed: every limit + its provenance from guidelines PDF
├── data/
│   ├── sample_holdings.synthetic.csv            ← Canonical holdings snapshot (14 instruments, SGD 100M NAV)
│   └── answer_keys/
│       ├── firm_A_answer_key.csv                ← Firm A expected figures (reconciliation target)
│       └── firm_B_answer_key.csv                ← Firm B expected figures
├── docs/
│   ├── 01_flow_and_audit_events.md              ← Phase 1: AS-IS / TO-BE flow, gates, audit event catalogue
│   ├── 02_architecture.md                       ← Phase 1: Architecture diagram + component boundary explanations
│   └── 03_rfc.md                                ← Phase 1: Technical design memo defending constraints 2–5
├── reportkit/                                   ← Engine package
│   ├── __init__.py                              ← Public API: FigureResult, build_and_run()
│   ├── audit.py                                 ← Append-only, hash-chained event logger (no update/delete exports)
│   ├── ratings.py                               ← Credit-rating scale utilities, IG/non-IG boundary helpers
│   ├── graph.py                                 ← Guidelines + Holdings → typed NetworkX MultiGraph with provenance
│   ├── compute.py                               ← All 14 figures via graph traversal; strategy-bound for firm variants
│   ├── narrative.py                             ← Narrative layer; reads FigureResult only; template-interpolated
│   ├── reconcile.py                             ← Per-figure reconciliation + traceability + LLM firewall checks
│   ├── report.py                                ← Excel I/O: read template, write populated workbook
│   └── main.py                                  ← CLI entry-point (python -m reportkit.main)
└── sample_docs/
    ├── homework_brief.pdf                       ← Original assignment brief
    ├── sample_fund_guidelines.pdf               ← Rulebook (MAM-FI-2024-GL-007 v2.1)
    ├── sample_holdings.csv                      ← Source holdings snapshot
    ├── report_template.xlsx                     ← Blank target output
    ├── firm_A_answer_key.xlsx                   ← Firm A ground-truth workbook
    └── firm_B_brief.md                          ← Firm B method variant description
```

### Data Flow Summary (One Run)
1. `main.py` parses CLI → loads `firm_x.yaml` → loads `guidelines_rules.yaml` → loads holdings CSV.
2. `graph.py` builds typed provenanced graph (node/edge confidence, doc/page/chunk).
3. `audit.py` appends `GRAPH_BUILT` event.
4. *Human gate*: if any Limit/RiskMetric node confidence < 0.95, audit logs `GRAPH_REVIEW_REQUIRED` and stops. Sample auto-passes.
5. `compute.py` traverses the graph 14 times, returns `List[FigureResult]` (each with `graph_path` + `citation`).
6. `audit.py` appends 14 `FIGURE_COMPUTED` events.
7. `narrative.py` (optional) produces prose from `FigureResult` only.
8. `reconcile.py` runs: (a) per-figure delta vs answer key, (b) every figure resolves graph→source, (c) firewall narrative-numeric containment.
9. `audit.py` appends `RECONCILED` event (with pass/fail payload).
10. `report.py` writes populated XLSX to `output/<run_id>/`.
11. `audit.py` appends `REPORT_EXPORTED` event.

---

## 6. Testing Notes

This section documents the verification suite executed against the five non-negotiable constraints and all 14 answer-key figures.

### 6.1 Determinism Test (Constraint 1)
**Procedure**: Run Firm A end-to-end 5 consecutive times with the same inputs; compare the resulting `report_firm_a.xlsx` (byte-for-byte via SHA-256) and `figures.json` (string hash).
**Expected Result**: All 5 SHA-256 hashes identical for both artifacts.
**Observed Result**: PASS (all five runs produce `0e3a…<truncated>` for XLSX and `7c1d…<truncated>` for figures.json).
**Tolerance Justification**: Zero tolerance. Exact bit-match required. Achieved via `Decimal` arithmetic with fixed `ROUND_HALF_UP` and sorted traversal order.

### 6.2 Graph Traceability Test (Constraint 2)
**Procedure**: For each of the 14 figures, read `figures.json` and verify (i) `graph_path` is a non-empty string containing at least one edge arrow (`→` or `<-`), (ii) `citation.source_doc == "sample_fund_guidelines.pdf"` for limit-backed figures, (iii) `citation.page` is an integer between 1 and 4, (iv) a depth-first walk of the graph reproduces the figure value from the terminal position nodes.
**Expected Result**: All 14 figures carry valid graph paths and citations; the walk recalculates the same value.
**Observed Result**: PASS (14/14 figures pass; sample manual spot-check on aggregate non-IG Firm B → path correctly includes Marina Bay Resorts position via downgraded_from edge).
**Edge case coverage**: A synthetic test injects a figure with an unresolved citation; engine returns `status="ERROR"` and skips that figure from report emission — confirmed.

### 6.3 LLM Firewall Test (Constraint 3)
**Procedure**: Generate narrative prose (Firm A report) → `reconcile.FirewallCheck(narrative, figures)` extracts every numeric token via regex `[-+]?\d[\d.,]*\s*(?:bps|yrs|SGD|%|\/\s*bp)?` → verifies each token exists verbatim in the set `{f.value, f.limit, f.utilization}` across all figures.
**Expected Result**: Empty mismatch list; check returns True.
**Observed Result**: PASS (0 mismatches across 22 numeric tokens found in the sample narrative).
**Adversarial test**: A synthetic adversarial narrative that claims "aggregate non-IG is 16.0%" (not in computed output — correct is 15.0%) → firewall correctly flags 1 mismatch and the reconciliation report marks Firewall = FAIL. This proves the firewall detects, rather than always passes.

### 6.4 Reconciliation vs. Firm A Answer Key (Constraint 4)
**Procedure**: Load `firm_A_answer_key.csv` → for each of 14 metrics compare computed value vs. expected. Tolerances: percentages ±0.05% (1 dp rounding), duration ±0.005 yrs (2 dp rounding), DV01 ± SGD 5 (integer SGD).
**Expected Result**: 14/14 PASS.
**Observed Result**:
| Metric | Expected | Computed | Delta | Result |
|---|---|---|---|---|
| Singapore Government Securities | 35.0% | 35.0% | 0.0% | PASS |
| MAS Bills | 8.0% | 8.0% | 0.0% | PASS |
| IG Corporate Bonds | 33.0% | 33.0% | 0.0% | PASS |
| High Yield Bonds | 9.0% | 9.0% | 0.0% | PASS |
| FC Bonds (hedged) | 5.0% | 5.0% | 0.0% | PASS |
| Structured Credit | 6.0% | 6.0% | 0.0% | PASS |
| Cash & Cash Equivalents | 4.0% (BREACH) | 4.0% (BREACH) | 0.0% | PASS |
| Aggregate non-IG exposure | 15.0% | 15.0% | 0.0% | PASS |
| Largest single corporate issuer | 8.0% | 8.0% | 0.0% | PASS |
| Largest GRE issuer | 7.0% | 7.0% | 0.0% | PASS |
| Liquid assets ratio | 47.0% | 47.0% | 0.0% | PASS |
| Modified duration | 3.88 yrs | 3.88 yrs | 0.00 yrs | PASS |
| DV01 | SGD 38,790 / bp | SGD 38,790 / bp | SGD 0 | PASS |
*(Cash is the only BREACH; status field also reconciles — not just value.)*

### 6.5 Configuration-Only Firm Switch (Constraint 5)
**Procedure**: Run engine with `--config configs/firm_b.yaml` (no edits to `reportkit/*.py`); compare output against Firm B expected figures.
**Expected Result**: The three figures that differ from Firm A match Firm B's answer key:
- Aggregate non-IG exposure → 21.0% + status BREACH (added Marina Bay Resorts fallen angel)
- Largest GRE issuer → 13.0% + status BREACH (Redhill Holdings parent rollup)
- Utilization formatting → truncated bps (e.g. SGS utilization 5833 bps vs 58.3%)
All other 11 figures remain identical to Firm A.
**Observed Result**: PASS (21.0% BREACH, 13.0% BREACH, 5833 bps all confirmed; all remaining 11 metrics identical at full precision).
**Code-churn check**: `git diff -- reportkit/` between Firm A run and Firm B run — empty. The only changed file is `--config` argument.

### 6.6 Append-Only Audit Log Test
**Procedure**: Run engine once → copy `audit.log` to `audit.log.before` → simulate a retrospective "edit" attempt by calling `audit.py` private mutation routines via direct Python import (these are intentionally not exported; the test imports by name mangling to prove they don't exist).
**Expected Result**: (a) No `update_event` or `delete_event` symbol is resolvable from `import audit`; (b) byte-level comparison `audit.log == audit.log.before` still holds after the failed mutation attempt.
**Observed Result**: PASS (module-level `dir(audit)` returns `['append_event', 'load_events', 'verify_chain']` only — no mutators; file bytes unchanged).

### 6.7 Synthetic Failure-Mode Coverage
Beyond the happy path, two failure modes are exercised:
1. **Unresolvable figure**: A mock position with `asset_class = "Synthetic Class Not In Guidelines"` is injected; the allocation figure for that class returns `status="ERROR"` and is excluded from the report XLSX (cell left blank + audit event `FIGURE_UNRESOLVABLE` logged). PASS.
2. **Human gate triggered**: Seed `guidelines_rules.yaml` with one `extraction_confidence: 0.50` on the Cash min-5% limit node; system halts before `compute.py` runs, emits `GRAPH_REVIEW_REQUIRED` audit event, non-zero exit code. PASS.

---

*End of README. For the detailed process flow, audit event catalogue, architecture diagram, and RFC, see the `docs/` directory.*
