
# Specification-Driven Development (SDD)

This project was built using **Specification-Driven Development** — a methodology where the full specification is written and validated *before* any implementation begins.

---

## Core principle

> Code is the last artefact, not the first.

In SDD, the sequence is:

```
Constitution → Specification → Plan → Tasks → Code
```

Each layer must be validated before the next one starts. Skipping layers is the primary cause of rework.

---

## The four layers

### 1. Constitution (`docs/constitution.md`)

The constitution defines **immutable constraints** that cannot change without explicit sign-off:

- Tech stack choices (locked per major version)
- Coding standards (formatter, linter, type checker)
- Data rules (storage layout, idempotency guarantees)
- Security rules (secret handling, auth model)
- Operational rules (run schedule, rate limits)
- Definition of Done (what "shipped" means)

The constitution answers: *what can never change, and why?*

### 2. Specification (`docs/specification.md`)

The specification defines **observable behaviour** — what the system does from the outside, independent of how it does it:

- Functional requirements (FR-01 … FR-N): one per user-visible behaviour
- Non-functional requirements (NFR-01 … NFR-N): performance, security, reliability bounds
- Data shapes: the exact JSON schema for stored records and API responses
- Acceptance criteria (AC-01 … AC-N): concrete, testable pass/fail conditions

The specification answers: *what must the system do, and how do we know it's done?*

Tests are defined in the specification **before** implementation. The acceptance criteria become the test cases.

### 3. Plan (`docs/plan.md`)

The plan defines **how** the specification will be implemented:

- Architecture diagram
- Repository layout
- Module contracts (function signatures, return types)
- Storage key structure
- API routes and auth model
- Deployment steps

The plan answers: *which modules exist, what do they do, and how do they connect?*

No code is written yet. The plan is reviewed against the specification to confirm that every FR and AC maps to at least one module or route.

### 4. Tasks (`docs/tasks.md`)

Tasks are **atomic work units** derived from the plan:

- Each task targets a single module or subsystem
- Each task includes explicit acceptance criteria (a subset of the spec's ACs)
- Tasks are estimated (1–4 h) and dependency-ordered
- A task is **done** only when its acceptance criteria pass

Tasks answer: *what exactly needs to be built, in what order?*

---

## Why SDD

| Problem | SDD response |
|---|---|
| "We built the wrong thing" | Spec validated before any code |
| "The tests don't match the spec" | AC defined in spec, tests derived from AC |
| "Why does this work this way?" | Every decision traces back to a spec requirement |
| "The architecture changed midway" | Plan is locked before tasks begin |
| "We added scope without knowing" | Tasks are derived from plan, not invented during coding |

---

## SDD in this project

| Layer | File | Status |
|---|---|---|
| Constitution | [`docs/constitution.md`](constitution.md) | Stable |
| Specification | [`docs/specification.md`](specification.md) | Stable |
| Plan | [`docs/plan.md`](plan.md) | Stable |
| Tasks | [`docs/tasks.md`](tasks.md) | Living document |

The full feature set of StackRadar was specified and planned before the first line of `src/` was written. The test files in `tests/` were stubbed from the acceptance criteria in `docs/specification.md`.

---

## Adapting SDD

SDD is not Waterfall. The constitution and specification can be updated — but only through an explicit change proposal, not silently during implementation. A PR that changes behaviour without a corresponding spec update is rejected.

For small projects or solo work, the four documents can be lightweight (a few hundred lines total). The discipline matters more than the volume.
