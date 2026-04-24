# Hyperloop Specification Index

Hyperloop is a spec-to-code reconciler. Specs declare desired behavior. Code is actual behavior. Hyperloop continuously detects gaps and dispatches AI agents to close them.

## Specs

| Spec | Purpose |
|---|---|
| [Architecture](architecture.spec.md) | System identity, two-subsystem design, data model, port inventory |
| [Reconciler](reconciler.spec.md) | Drift detection tiers, PM intake, alignment audit, garbage collection |
| [Task Processor](task-processor.spec.md) | Phase map, step execution, deterministic workflow, retry |
| [Ports](ports.spec.md) | Contracts for all seven port interfaces |
| [Prompt Composition](prompt-composition.spec.md) | Three-layer kustomize prompt model, hot-reload |
| [Observability](observability.spec.md) | Observer pattern, event catalog, adapter behavior |
| [State Management](state-management.spec.md) | Persistence, state branch, garbage collection, summaries |
| [Dashboard](dashboard.spec.md) | Read-only observation and control UI |
| [Non-Functional Requirements](nfr.spec.md) | Fakes over mocks, contract tests, scenario coverage, type safety |
