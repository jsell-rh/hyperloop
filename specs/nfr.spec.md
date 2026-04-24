# Non-Functional Requirements Specification

## Purpose

Cross-cutting quality requirements that apply to all hyperloop code. These constrain how the system is built and tested, not what it does.

## Requirements

### Requirement: No Mocks - Use Fakes

The system MUST NOT use unittest.mock, MagicMock, patch, or any mocking library. All test doubles SHALL be fakes: complete in-memory implementations of port interfaces that implement the full contract.

#### Scenario: Fake implements full port contract

- GIVEN a port interface (e.g., StateStore) with 15 methods
- WHEN a fake is created (e.g., InMemoryStateStore)
- THEN the fake implements all 15 methods with real behavior
- AND the fake is a first-class, tested, reusable artifact

#### Scenario: Fake passes contract tests

- GIVEN a contract test suite for the StateStore port
- WHEN the contract tests run against InMemoryStateStore
- THEN all tests pass
- AND when the same contract tests run against the real GitStateStore
- THEN all tests also pass
- AND behavioral equivalence is verified

#### Scenario: No mock imports in test code

- GIVEN the test suite
- WHEN scanned for imports
- THEN no file imports from unittest.mock
- AND no file uses MagicMock, patch, or Mock

### Requirement: Contract Tests for Every Port

Every port SHALL have contract tests that validate behavioral equivalence between the fake and all real adapter implementations.

#### Scenario: New adapter must pass existing contracts

- GIVEN contract tests exist for the Runtime port
- WHEN a new runtime adapter is implemented (e.g., CloudRuntime)
- THEN it MUST pass all existing contract tests
- AND divergence from the fake's behavior is caught by the test suite

#### Scenario: Contract test parameterization

- GIVEN contract tests for StateStore
- WHEN the tests are executed
- THEN they run against every implementation (InMemoryStateStore, GitStateStore)
- AND failures in any implementation are reported independently

### Requirement: Test Coverage for Every Scenario

Every scenario in every spec file SHALL have at least one corresponding automated test.

#### Scenario: Spec scenario maps to test

- GIVEN a scenario "Coverage gap detected" in reconciler.spec.md
- WHEN the test suite is reviewed
- THEN at least one test exists that exercises: a spec without matching tasks, the reconciler identifying the gap, and the PM intake being triggered

#### Scenario: New scenario requires new test

- GIVEN a new scenario is added to a spec file
- WHEN the change is reviewed
- THEN a corresponding test MUST be added in the same change
- AND the test follows the GIVEN/WHEN/THEN structure from the scenario

### Requirement: Fakes Live in Tests Directory

Fakes SHALL be organized alongside tests, not in production code.

#### Scenario: Fake location

- GIVEN an InMemoryStateStore fake
- WHEN looking for it in the codebase
- THEN it is located at tests/fakes/state.py
- AND not in src/hyperloop/

### Requirement: Pure Domain Tests Without Fakes

Domain logic (pure functions, value objects) SHALL be tested directly with real objects, not fakes. Fakes are only for port boundaries.

#### Scenario: Domain function tested directly

- GIVEN the decide() function is pure (no I/O)
- WHEN testing it
- THEN real Task, World, and WorkerState objects are constructed
- AND no fakes or mocks are used
- AND the test asserts on the returned Action list

### Requirement: Type Hints - Full Coverage

Every function signature and every non-obvious variable SHALL have type hints. The `Any` type is banned.

#### Scenario: No Any in codebase

- GIVEN the full source tree
- WHEN type-checked in strict mode
- THEN no `Any` type annotations exist
- AND the type checker reports zero errors

### Requirement: Layered Testing

Tests SHALL be organized in layers:

| Layer | What it tests | Uses |
|---|---|---|
| Domain | Pure logic (decide, phase transitions) | Real domain objects only |
| Port contract | Behavioral equivalence across implementations | Fakes and real adapters |
| Integration | Adapter behavior against real systems | Real systems (git repos, APIs) |
| End-to-end | Full reconciler + task processor cycle | Real state store + fake runtime |

#### Scenario: Domain tests are fast

- GIVEN domain tests use no I/O
- WHEN the domain test suite runs
- THEN it completes in under 1 second

#### Scenario: Integration tests are marked slow

- GIVEN integration tests hit real systems
- WHEN they are defined
- THEN they are marked with @pytest.mark.slow
- AND they can be skipped in fast feedback loops
