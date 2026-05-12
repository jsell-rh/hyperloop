# Prompt Composition Specification

## Purpose

Agent prompts are composed from three layers resolved via kustomize. This enables framework defaults, team customization, and automated refinement to coexist without conflict. Every agent role — decomposition, implementer, verifier, merge resolver, integration summarizer — uses the same composition model. The prompt composer is shared infrastructure: it is injected into AgentRuntime adapters by the composition root. Adapters call the composer with structured context and an optional epilogue string. The domain layer does not interact with the composer directly.

## Requirements

### Requirement: Three-Layer Composition

Prompts SHALL be composed from three layers, applied in order:

| Layer | Source | Who writes it | What it provides |
|---|---|---|---|
| Base | Hyperloop package | Framework maintainers | Core agent identity and behavior (`prompt`) |
| Project overlay | `.hyperloop/agents/` in team's repository | Project team | Project-specific rules and customizations (`guidelines`, `prompt` patches) |
| Process overlay | `.hyperloop/agents/process/` in team's repository | Automated tooling or team | Learned or refined rules (`guidelines`) |

All three layers are resolved via a single `kustomize build` invocation, producing a unified set of agent templates.

#### Scenario: Base layer provides identity

- GIVEN no overlays exist in the team's repository
- WHEN a prompt is composed for the implementer role
- THEN the base layer's prompt is used as-is
- AND it defines the agent's core identity and behavior

#### Scenario: Project overlay adds guidelines

- GIVEN a team has added implementer guidelines in `.hyperloop/agents/`
- WHEN a prompt is composed
- THEN the base prompt is combined with the team's guidelines
- AND the guidelines appear as a distinct section in the composed prompt

#### Scenario: Process overlay augments project overlay

- GIVEN both project and process overlays define guidelines for the implementer
- WHEN a prompt is composed
- THEN both sets of guidelines are included
- AND the final guidelines list is: project overlay guidelines followed by process overlay guidelines (concatenated in order)
- AND process overlay guidelines augment, not replace, project guidelines

#### Scenario: All roles use the same composition model

- GIVEN the decomposition agent has a base prompt
- WHEN a team adds decomposition guidelines in their project overlay
- THEN the prompt is composed with the same three-layer model as any other agent role

### Requirement: Agent Template Schema

Each agent template produced by kustomize build SHALL be a YAML document with `kind: Agent` and contain:

| Field | Type | Description |
|---|---|---|
| name | string | Role identifier (e.g., "implementer", "decomposer", "verifier") |
| prompt | string | Core prompt text, MAY contain substitution placeholders |
| guidelines | list of string | Additional rules from overlays (empty list if none) |

#### Scenario: Guidelines as discrete list items

- GIVEN a project overlay adds two guidelines for the implementer
- WHEN the template is loaded
- THEN guidelines is a list of two strings
- AND each guideline is a discrete unit that can be added or removed independently

#### Scenario: Substitution placeholders

- GIVEN a prompt template contains `{task_id}` and `{spec_ref}`
- WHEN the prompt is composed for task 5 with spec_path "specs/auth.spec.md" and spec_blob_sha "abc123"
- THEN `{task_id}` is replaced with "5"
- AND `{spec_ref}` is replaced with "specs/auth.spec.md@abc123" (composed from spec_path and spec_blob_sha)

#### Scenario: Unknown placeholder produces error

- GIVEN a prompt template contains `{unknown_field}`
- WHEN composition is attempted
- THEN a compose-time error is raised
- AND the agent is not launched with an unresolved placeholder

### Requirement: Context Injection

At compose time, the prompt composer SHALL inject runtime context as additional sections appended after the template. The exact sections depend on the agent role and available context.

| Context | When included | Content |
|---|---|---|
| Spec content | Task and verification prompts | The spec at the pinned blob SHA |
| Events | Task prompts on retry | Prior failure events, verification failure rationale |
| Epilogue | All prompts (when provided by the adapter) | Runtime-specific instructions |

#### Scenario: First-round task prompt

- GIVEN task 5 at round 0 (first attempt)
- WHEN the prompt is composed
- THEN it contains: base prompt + guidelines + spec content
- AND no events section (no prior failures)

#### Scenario: Retry prompt with failure context

- GIVEN task 5 at round 1 with TaskFailed events from round 0
- WHEN the prompt is composed
- THEN it contains: base prompt + guidelines + spec content + events
- AND the events section includes the failure details from round 0

#### Scenario: Epilogue injected by adapter

- GIVEN an AgentRuntime adapter provides a non-empty epilogue string (e.g., completion signaling instructions)
- WHEN the prompt is composed
- THEN the epilogue is appended as the final section

#### Scenario: No epilogue

- GIVEN an AgentRuntime adapter provides an empty epilogue string
- WHEN the prompt is composed
- THEN no epilogue section is included in the output

#### Scenario: Decomposition prompt

- GIVEN OutOfSync specs with diffs, events, and cross-spec task state
- WHEN the decomposition agent's prompt is composed
- THEN it contains: base prompt + guidelines + spec content at current SHA + diff from last Synced SHA + prior events (if any) + current task state across all specs (for cross-spec dependency awareness)

#### Scenario: Integration summarizer prompt

- GIVEN a spec has passed verification and is ready for trunk integration
- WHEN the `integration-summarizer` role's prompt is composed
- THEN it contains: base prompt + guidelines + spec content at pinned SHA + completed task names and descriptions + verification rationale
- AND the agent produces a structured response with a PR title and body

### Requirement: Hot-Reload

The prompt composer SHALL rebuild templates when overlay files change. Rebuild MUST NOT require a reconciler restart.

#### Scenario: Overlay change triggers rebuild

- GIVEN a team pushes changes to `.hyperloop/agents/`
- WHEN the reconciler detects the overlay directory has changed
- THEN it triggers a composer rebuild via `kustomize build`
- AND subsequent agents receive the updated templates

#### Scenario: Rebuild failure retains previous templates

- GIVEN invalid YAML is written to the process overlay
- WHEN the composer attempts a rebuild and `kustomize build` fails
- THEN the composer retains the previous known-good templates
- AND a probe event is emitted indicating the build failure
- AND the reconciler continues operating with the stale templates until the overlay is fixed

### Requirement: Validation

The prompt composer SHALL validate that all agent roles referenced in the system have corresponding templates in the kustomize output.

#### Scenario: Missing agent template detected

- GIVEN the reconciler expects a "verifier" role
- WHEN no Agent document named "verifier" exists in the kustomize output
- THEN the composer SHALL report an error listing the undefined role
- AND the reconciler SHALL NOT start with an incomplete configuration

#### Scenario: Extra templates are allowed

- GIVEN the kustomize output contains an Agent template for "experimental-reviewer"
- WHEN no part of the system references this role
- THEN the extra template is loaded without error
- AND it is available for future use

### Requirement: Directory Structure

The project SHALL organize prompt-related files as:

```
.hyperloop/
  agents/
    kustomization.yaml              # References base + patches
    {role}-patch.yaml               # Per-role overrides (optional)
    process/                        # Process overlay (kustomize Component)
      kustomization.yaml
      {role}-overlay.yaml           # Per-role guideline additions
```

The base agent definitions are bundled with the Hyperloop package and referenced by the project's `kustomization.yaml`.

#### Scenario: Minimal project setup

- GIVEN a team wants to use Hyperloop with default agent behavior
- WHEN they create `.hyperloop/agents/kustomization.yaml` referencing only the base
- THEN all agents use their default prompts with no customization

#### Scenario: Team adds project-specific guidelines

- GIVEN a team wants implementers to always write tests first
- WHEN they add `implementer-patch.yaml` with a guidelines entry
- THEN the implementer's composed prompt includes "always write tests first"
- AND other agent roles are unaffected
