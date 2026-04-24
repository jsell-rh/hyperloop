# Prompt Composition Specification

## Purpose

Agent prompts are composed from three layers resolved via kustomize. This enables framework defaults, team customization, and runtime learning to coexist without conflict. Every agent role — PM, implementer, verifier, auditor, process-improver — uses the same composition model.

## Requirements

### Requirement: Three-Layer Composition

Prompts SHALL be composed from three layers, applied in order:

| Layer | Source | Who writes it | What it targets |
|---|---|---|---|
| Base | Hyperloop repository | Framework maintainers | Core agent identity (`prompt`) |
| Project overlay | Team's repository | Project team | Project-specific rules (`guidelines`, `prompt`) |
| Process overlay | `.hyperloop/agents/process/` | Process-improver agent | Learned rules (`guidelines`) |

#### Scenario: Base layer provides identity

- GIVEN no overlays exist
- WHEN a prompt is composed for the implementer role
- THEN the base layer's prompt is used
- AND it defines the agent's core identity and behavior

#### Scenario: Project overlay adds guidelines

- GIVEN a team has added implementer guidelines in their overlay
- WHEN a prompt is composed
- THEN the base prompt is combined with the team's guidelines
- AND the guidelines appear as a distinct section in the composed prompt

#### Scenario: Process overlay refines guidelines

- GIVEN the process-improver has written implementer guidelines
- WHEN a prompt is composed
- THEN both project and process guidelines are included
- AND process overlay guidelines augment (not replace) project guidelines

#### Scenario: All roles use the same model

- GIVEN the PM has a base prompt in the hyperloop repository
- WHEN a team adds PM guidelines in their project overlay
- THEN the PM's prompt is composed with the same three-layer model as any worker agent

### Requirement: Agent Template Schema

Each agent template SHALL contain:

| Field | Description |
|---|---|
| name | Role identifier (e.g., "implementer", "pm", "verifier") |
| prompt | Core prompt text, may contain substitution placeholders |
| guidelines | Additional rules from overlays (empty string if none) |

### Requirement: Context Injection

At compose time, the prompt composer SHALL inject runtime context as additional sections appended after the template:

| Context | When included | Content |
|---|---|---|
| Spec content | Task worker prompts | The spec at the pinned SHA |
| Findings | Task worker prompts (after first round) | Previous round's review detail |
| Signal feedback | Task worker prompts (after rejection) | The human's rejection message |
| Runtime epilogue | All worker prompts | Runtime-specific instructions |

#### Scenario: First-round prompt

- GIVEN task-001 at phase "implement", round 0
- WHEN the prompt is composed
- THEN it contains: prompt + guidelines + spec content + epilogue
- AND no findings section (first attempt)

#### Scenario: Retry prompt with findings

- GIVEN task-001 at phase "implement", round 1 with findings from round 0
- WHEN the prompt is composed
- THEN it contains: prompt + guidelines + spec content + findings + epilogue
- AND the findings section includes the verifier's feedback from round 0

#### Scenario: Retry prompt with signal feedback

- GIVEN task-001 was rejected at a signal step with message "add timeout handling"
- WHEN the prompt is composed for the retry
- THEN the signal message is included in the findings section

### Requirement: Prompt Provenance

Each section of a composed prompt SHALL carry provenance metadata indicating its source layer (base, project-overlay, process-overlay, spec, findings, runtime).

#### Scenario: Dashboard displays provenance

- GIVEN a composed prompt with sections from multiple layers
- WHEN the dashboard displays the prompt
- THEN each section is annotated with its source layer

### Requirement: Hot-Reload

The prompt composer SHALL rebuild when the reconciler detects overlay changes. Rebuild MUST NOT require an orchestrator restart.

#### Scenario: Overlay change triggers rebuild

- GIVEN a team pushes changes to .hyperloop/agents/
- WHEN the reconciler detects the overlay SHA has changed
- THEN it triggers a composer rebuild
- AND subsequent prompts use the updated templates

#### Scenario: Process-improver triggers rebuild

- GIVEN the process-improver writes new guidelines to .hyperloop/agents/process/
- WHEN the rebuild occurs
- THEN subsequent workers receive the updated guidelines

### Requirement: Directory Structure

The project SHALL organize prompt-related files as:

```
.hyperloop/
├── agents/
│   ├── kustomization.yaml              # composition point (references base + overlays)
│   └── process/                        # kustomize Component
│       ├── kustomization.yaml
│       └── {role}-overlay.yaml         # per-role guideline patches
```

### Requirement: Process Definition in Kustomize Output

The phase map SHALL be defined as a `kind: Process` document in the kustomize output alongside `kind: Agent` documents.

#### Scenario: Phase map loaded from kustomize

- GIVEN a kustomization that produces Agent and Process documents
- WHEN the composer loads templates
- THEN it extracts Agent documents as prompt templates
- AND extracts the Process document as the phase map
