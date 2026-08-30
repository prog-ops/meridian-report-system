# RFC: Auditable Guideline Reporting System

## Problem

We need to generate a periodic fund compliance report from:

- investment guidelines,
- a holdings snapshot,
- a fixed report template,
- and firm-specific computation conventions.

The system must satisfy five hard constraints:

1. Every reported number must be reproducible.
2. Every reported number must be traceable through a knowledge graph.
3. No reported number may be produced or altered by an LLM.
4. The system must reproduce Firm A's answer key.
5. The system must be reconfigurable to Firm B without engine-code changes.

The audit environment is strict. It is not enough for figures to be correct.
The system must also prove how each figure was produced, from which source
passage, by which method, and that nothing was quietly edited.

## Core Design Principle

The architecture separates three concerns:

1. **Semantic grounding**

    Guidelines and holdings are modeled as a knowledge graph.

2. **Deterministic computation**

    All figures are computed by a pure computation layer that traverses the graph.

3. **Language generation**

    If an LLM is used, it only produces narrative commentary and is firewalled from numeric computation. This separation is the heart of the design.

## Why a Knowledge Graph?

Portfolio rules are relational, not flat.

Examples:

- an allocation limit belongs to an asset class,
- an aggregate cap receives contributions from asset classes,
- a risk metric has a limit,
- a breached risk metric has an action,
- an action has an owner,
- an issuer may roll up to a parent issuer,
- a position belongs to an asset class and is issued by an issuer.

A graph lets the system compute figures and also explain them.

For example:

```text

(Position)-\[:BELONGS\_TO]->(AssetClass:Singapore Government Securities)

-\[:HAS\_LIMIT]->(Limit:allocation:Singapore Government Securities)

-\[:HAS\_PROVENANCE]->(Chunk:chunk\_sec2\_alloc\_sgs)

```

