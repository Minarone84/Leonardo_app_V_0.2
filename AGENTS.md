# Leonardo V2 - Agent Instructions

These instructions define how Codex, Goblin, or any implementation agent must work inside the Leonardo V2 repository.

The word "Codex" in older sections of this file means the active implementation agent. When the user refers to "Goblin", Goblin must follow the same rules unless the user gives a narrower instruction for the current task.

The primary goal is safe, surgical, reviewable software work.

---

# 0. Leonardo V2 Rebuild Scope

Leonardo V2 is a clean rebuild, not an in-place continuation of old Leonardo.

Old Leonardo source may be used only as reference material unless a task explicitly approves importing, adapting, or reusing a specific old module. Do not copy old source into active `src/leonardo/` as a shortcut. Every old module proposed for reuse must be audited for dependencies, ownership, contracts, imports, tests, and fit with the V2 architecture before it is introduced.

The active V2 direction is:

1. contract-aware Core foundation;
2. app/runtime/async infrastructure;
3. audit/runtime observability;
4. user/session policy;
5. window/action/operation tracking;
6. GUI shell with visible windows and stable action IDs;
7. Data Manager and domain services later;
8. selective old-code reuse only after focused audit.

Do not resurrect old Analysis Suite, Research Validation, backtesting, signal generation, trading, agents, Decisor/RL, or other old-domain behavior unless explicitly scoped in a future task.

---

# 0.1 Current Core Priority Order

The accepted Leonardo V2 Core priority order is:

1. `CORE-00` repo hygiene / old-code quarantine;
2. `CORE-01` Contract Kernel;
3. `CORE-02` App Runtime Foundation;
4. `CORE-03` Async Runtime + TaskManager;
5. `CORE-04` AuditLog + sinks;
6. `CORE-05` StateStore;
7. `CORE-06` SessionManager + UserPolicy;
8. `CORE-07` ServiceRegistry;
9. `CORE-08` WindowRegistry + ActionRegistry + OperationRegistry;
10. `CORE-09` ErrorRouter;
11. `CORE-10` Runtime Manager backend snapshots;
12. `CORE-11` ProcessManager;
13. `CORE-12` Connection/WebSocket tracking base.

Do not skip ahead to Data Manager, GUI implementation, connection reuse, workspace reuse, charting, financial tools, or old-code import before the current approved phase allows it.

---

# 0.2 V2 Repository Layout Rules

The expected Leonardo V2 repository root is:

```text
Leo_V2/
    AGENTS.md
    .gitignore
    pyproject.toml
    docs/
    historical_data/
    runs/
    src/
    tests/
    tmp/
```

All README-style project documentation must live under `docs/`. Root-level documentation should be limited to files explicitly approved by the user.

Importable Python contracts live under:

```text
src/leonardo/contracts/
```

Human-readable contract documentation lives under the docs contract area, using the current project folder convention approved by the user, such as:

```text
docs/contracts_docs/
```

Tests live under:

```text
tests/
```

Do not create broad empty folder trees ahead of the approved phase. Create only the folders and files needed by the current task.

---

# 0.3 Contracts and Contract-Aware Core

Leonardo V2 must be contract-aware, not contract-frozen.

The early goal is not to define every domain contract permanently. The early goal is to build a Core that can register, inspect, validate, version, report, and evolve contracts safely.

Rules:

- Shared runtime/importable contracts belong under `src/leonardo/contracts/`.
- Core may depend on kernel contracts and the contract registry.
- Domain systems should register their own contracts when their phase arrives.
- Core must not become a god object that imports every domain contract directly.
- Contract changes must be versioned, adapted, or blocked explicitly.
- Contract validation failures must be reportable and auditable.
- GUI code must not invent contracts locally.
- Old contracts may be reused only after an explicit import/adaptation audit.

Kernel contracts should stay small and stable. Domain contracts may evolve through explicit versioning and validation.

---

# 0.4 V2 Observability Rules

Leonardo V2 must be observable from the beginning.

Core must support, as the architecture grows:

- full audit logging for app lifecycle, users/sessions, windows, actions, operations, tasks, processes, services, errors, connections, and websockets;
- runtime state as current truth;
- audit history as historical truth;
- stable IDs for windows, actions, operations, tasks, processes, services, and connections;
- a Runtime Manager / Runtime Inspector surface that can display open windows, recent actions, active operations, active tasks, processes, connections, errors, and session logs;
- no fake cancellation or fake success states.

Every GUI window must eventually have a stable `window_id`. Every button or menu action must eventually have a stable `action_id`. Every meaningful workflow must eventually have an `operation_id`.

---

# 0.5 Old-Code Quarantine and Reuse Rule

Old Leonardo code may be valuable, especially connection, workspace, chart, financial-tool, and complex working subsystems. It must still be treated as quarantined reference material until explicitly approved for reuse.

Before reusing old code, the agent must audit:

- imports and dependencies;
- hidden coupling to old Analysis Suite or old Data Manager behavior;
- contracts and public APIs;
- ownership boundaries;
- tests and validation requirements;
- whether reuse should be direct copy, adaptation, wrapper, or rewrite;
- whether the module belongs in active `src/leonardo/` or in a reference-only location.

Do not copy old modules into active V2 source merely because they worked before. Working old code can still be architecturally poisonous in a clean rebuild.

---

# 0.6 Legacy Rule Sections

Some later sections in this file preserve old Leonardo domain rules for Data Manager, financial tools, charting, historical charts, and persistence. In Leonardo V2 these sections are legacy reference rules unless the current task explicitly scopes that domain.

When a V2 task is scoped only to Core, contract kernel, app runtime, async runtime, audit, state, user policy, window/action/operation tracking, or Runtime Manager foundations, do not introduce old Data Manager, Analysis Suite, chart, backtesting, trading, or financial-tool implementation work.

---

# 1. Core Working Protocol

Every code task must follow this sequence:

1. Audit
2. Update
3. Validation

This protocol is mandatory.

Do not skip Audit.
Do not skip Validation.
Do not mix unrelated changes into the same task.
Respect all applicable AGENTS.md instructions in the repository.
Do not ignore AGENTS.md.
If there are multiple AGENTS.md files in nested folders, apply the most specific one for each audited file.
If an AGENTS.md instruction conflicts with this task, stop and report the conflict instead of guessing.

---

# Phase-Scoped Aggregation Rule

The Audit → Update → Validation protocol remains mandatory.

For large multi-step features, the user may define a phase-scoped task that aggregates multiple related subpatches when all included changes share one architectural responsibility and the prompt explicitly lists:

- the phase name;
- every included subpatch name;
- allowed files or subsystems;
- forbidden behavior;
- validation commands;
- stop conditions.

Aggregation must not mix unrelated responsibilities.

Low-risk aggregation is allowed for:
- documentation sync plus final audit;
- model-only contracts and focused tests;
- test-only hardening;
- report-only or preflight-only services when explicitly approved;
- read-only docs/source consistency updates.

High-risk changes must remain isolated unless explicitly approved:
- persistence writes;
- dataframe loading;
- runtime execution;
- projection generation;
- backtesting;
- PnL/profit validation;
- signal generation;
- trading/order behavior;
- GUI/CoreBridge wiring;
- broad refactors;
- service-call orchestration across multiple owners.

Each aggregated task must still include:
- Audit;
- Update;
- Validation;
- Original-Code Comparison.

Validation must cover every included subpatch and confirm the final diff is limited to the declared scope.

## 1.1 Audit

Before editing code, inspect the relevant files and understand the current behavior.

During Audit:

- Do not modify files.
- Identify the actual problem.
- Identify the files involved.
- Identify the smallest safe change.
- Check existing project patterns before introducing new ones.
- Check whether tests already exist for the affected behavior.
- Identify the relevant contracts before proposing changes.
- Report risks before editing.
- Separate confirmed issues from suspected issues.
- Do not perform speculative refactors.

Audit output must include:

- Problem summary
- Relevant files
- Current behavior
- Relevant contracts
- Proposed change
- Risk level
- Tests or validation commands to run
- Additional findings, if any

No code changes are allowed during Audit unless the user explicitly requests immediate editing.

---

## 1.2 Update

Only after the Audit, apply the smallest safe change.

During Update:

- Change only what is necessary.
- Preserve existing public APIs unless explicitly instructed.
- Preserve existing behavior outside the requested scope.
- Do not perform opportunistic refactors.
- Do not rename files, classes, methods, functions, modules, or concepts unless the task explicitly requires it.
- Do not introduce new dependencies unless explicitly approved.
- Do not rewrite working systems just because they look imperfect.
- Keep changes focused, readable, and reversible.
- Preserve existing contracts unless changing the contract is the explicit purpose of the task.
- Do not touch unrelated files.
- Do not perform broad formatting changes unless formatting is the explicit task.

Update output must include:

- Files changed
- What changed
- Why it changed
- Any behavior intentionally left unchanged
- Any out-of-scope issues discovered but not changed

---

## 1.3 Validation

After every update, validate the result.

During Validation:

- Run the most relevant tests.
- If no test exists, explain what manual validation is needed.
- Check imports if files were moved, renamed, or newly referenced.
- Check whether the change creates dead code or broken references.
- Review the diff against the original code state.
- Confirm that each changed line is related to the requested task.
- Confirm that no unrelated behavior was modified.
- Confirm that no unrelated formatting churn was introduced.
- Confirm that no public API was changed unless explicitly requested.
- Confirm that no imports, names, files, modules, or package boundaries were changed unnecessarily.
- Confirm that no defensive checks, error handling, logging, audit hooks, or validation logic was removed accidentally.
- Confirm that comments and docstrings were not weakened or made less precise.
- Report failures honestly.
- Do not hide failing tests.
- Do not weaken tests to make them pass.
- Do not claim success unless validation actually passed.

Validation output must include:

- Commands run
- Test result
- Original-code comparison
- Failures, if any
- Remaining risks

---

# Sandbox Escalation and Test Execution Rules

Codex may request approval to run a command outside the sandbox only when sandbox execution fails and the command is required for validation.

Approved escalation is allowed only for narrow, explicit validation commands.

Allowed with explicit user approval:

- python -m py_compile <specific_file>
- python -m pytest <specific_test_file_or_directory>
- rg <read_only_search_pattern>
- git status --short
- git diff
- git diff --stat

Forbidden outside the sandbox unless explicitly approved as a separate task:

- git push
- git pull
- git reset
- git clean
- git checkout
- git restore
- git merge
- git rebase
- git commit
- pip install
- python scripts that modify files
- commands that delete, move, or rewrite files
- commands that access the network
- commands that launch the GUI application
- broad project-wide commands not required by the current task

When requesting escalation, Codex must state:

- The exact command to run
- Why sandbox execution failed
- Why the command is necessary
- Whether the command can modify files
- Whether the command uses network access
- Whether the command affects Git state

Codex must not request broad escalation.

Codex must not request session-wide escalation when single-command approval is sufficient.

After any approved outside-sandbox validation command, Codex must report:

- Exact command run
- Result
- Any failures
- Whether files changed
- Whether Git status changed

When running validation commands outside the sandbox, Codex should prefer this pattern:

    git status --short
    <approved validation command>
    git status --short

The first status check records the pre-validation state.
The second status check confirms whether validation created, modified, or removed files.

`git status --short` is read-only and does not modify repository state.

# 2. Surgical Change Rule

Every code change must be surgical.

A surgical change is:

- Minimal
- Task-bound
- Easy to review
- Limited to the requested behavior
- Free from unrelated formatting churn
- Free from opportunistic refactoring
- Free from unrelated naming changes
- Free from unrelated import reshuffling
- Free from speculative architecture work

Codex must validate every update against the original code state by reviewing the diff and confirming that all changed lines are related to the requested task.

If unrelated changes are found, Codex must either:

1. Revert those unrelated changes, or
2. Report them clearly and wait for explicit approval before keeping them.

The final validation report must include a section named:

## Original-Code Comparison

This section must state:

- Files compared
- Whether the diff is limited to the requested scope
- Any unrelated changes found
- Any behavior preserved intentionally
- Any contracts preserved intentionally

Do not modify nearby code merely because it appears imperfect.

Do not combine bug fixes, refactors, formatting, and documentation changes in one task unless explicitly requested.

Preserve the original structure unless changing the structure is the explicit purpose of the task.

---

# 3. General Behavior Rules

Codex must follow these general engineering rules:

- Prefer correctness over cleverness.
- Prefer explicit code over magical behavior.
- Prefer small surgical changes over broad rewrites.
- Prefer existing project patterns over inventing new ones.
- Preserve backward compatibility unless explicitly told otherwise.
- Do not introduce abstraction unless it removes real duplication or protects a real contract.
- Do not create speculative architecture for imagined future needs.
- Do not add placeholders, fake implementations, or temporary production logic.
- Do not silence errors unless the error is intentionally handled and documented.
- Do not catch broad exceptions without a clear reason.
- Do not change unrelated files.
- Do not format entire files unless formatting is the requested task.
- Do not optimize code unless performance is part of the requested task.
- Do not change behavior while cleaning up code.
- Do not remove code unless it is confirmed unused or explicitly requested.
- Do not introduce hidden global state.
- Do not bypass existing lifecycle or registration mechanisms.
- Do not make changes just because the code could be written differently.
- Do not turn a local fix into an architectural rewrite.
- Do not create duplicate replacement files with suffixes such as "new", "fixed", "final", "v2", or "backup".

The purpose of a task is to solve the assigned problem, not to redesign the project.

---

# 4. Scope Control

Before editing, determine the task scope.

A change is out of scope if it:

- Touches unrelated modules.
- Changes public interfaces unnecessarily.
- Alters behavior not mentioned in the task.
- Adds new dependencies.
- Moves files without explicit instruction.
- Renames existing concepts without explicit instruction.
- Converts working code to a different style just for consistency.
- Performs architectural cleanup not required by the task.
- Changes tests unrelated to the requested behavior.
- Changes documentation unrelated to the requested behavior.
- Changes formatting in files not otherwise being edited.

If an out-of-scope issue is found, report it under "Additional Findings" instead of fixing it immediately.

Out-of-scope findings may be proposed as separate future tasks.

---

# 5. Code Quality Rules

All code should be:

- Clear
- Deterministic
- Testable
- Maintainable
- Explicit about failure cases
- Consistent with nearby code
- Minimal without being cryptic
- Focused on one responsibility
- Safe against invalid state
- Easy to review in a diff

Avoid:

- Hidden global state
- Circular imports
- Large multi-responsibility functions
- Deeply nested conditionals when early returns are clearer
- Duplicate logic across modules
- Hardcoded paths unless explicitly required
- Silent fallbacks that hide broken state
- Runtime guessing when a contract should exist
- Implicit dependencies between unrelated layers
- Broad helper modules that become dumping grounds
- Clever one-liners that reduce readability
- Large functions that mix validation, transformation, persistence, and UI concerns

If the code needs a paragraph of explanation to justify why it is safe, it probably needs to be simpler.

---

# 6. Python Rules

Codex must follow these Python rules:

- Use type hints for new public functions and methods.
- Keep imports explicit.
- Avoid wildcard imports.
- Avoid import-time side effects.
- Keep module-level code minimal.
- Prefer dataclasses for structured data when appropriate.
- Prefer pathlib.Path over raw string path manipulation.
- Do not mutate input arguments unless explicitly documented.
- Do not use mutable default arguments.
- Do not swallow exceptions with empty except blocks.
- Do not use print for production logging unless the project already does so in that layer.
- Use existing logging, audit, or reporting mechanisms where available.
- Keep functions focused on one responsibility.
- Keep classes focused on one reason to change.
- Avoid circular imports.
- Avoid broad utility modules unless the project already has a clear pattern for them.
- Avoid changing import structure unless required by the task.
- Avoid changing public constructor signatures unless explicitly requested.
- Avoid changing public method names unless explicitly requested.
- Avoid changing return types unless explicitly requested.
- Avoid adding optional parameters to avoid fixing call sites.
- Prefer explicit validation at system boundaries.
- Prefer clear exceptions with actionable context.
- Prefer existing project exceptions or audit mechanisms when available.

---

# 7. Professional Documentation Rule

Comments and docstrings must be professional, technical, and objective.

They must not:

- Address the reader directly.
- Use conversational language.
- Include jokes or sarcasm.
- Include emotional language.
- Include personal opinions.
- Explain obvious code.
- Contain vague claims.
- Use phrases such as "you need to", "we just", "simple", "easy", or "obviously".

Comments and docstrings should explain:

- Intent
- Contracts
- Invariants
- Constraints
- Side effects
- Failure modes
- Lifecycle assumptions
- Non-obvious design decisions
- Compatibility requirements
- Reasons why an apparently unusual decision exists

Bad comment style:

    # You need to keep this here or the GUI gets angry.

Good comment style:

    # Service registration must complete before GUI window construction.
    # The GUI resolves runtime services through AppContext during startup.

Bad comment style:

    # Loop over items.

Good comment style:

    # Preserve declaration order because recipe materialization depends on
    # deterministic column ordering.

Comments must not be used to decorate obvious code.

Comments must document intent, not narrate syntax.

---

# 8. Docstring Rules

Use professional, extended docstrings for public modules, public classes, public functions, public methods, services, persistence components, lifecycle components, registry-facing components, and contract-facing code when behavior is non-trivial.

Docstrings must explain the relevant contract.

Docstrings should include, when applicable:

- Purpose
- Responsibilities
- Parameters
- Return value
- Raised exceptions
- Side effects
- Lifecycle assumptions
- Data contract assumptions
- Persistence contract assumptions
- Threading or async assumptions
- Notes about intentionally unsupported behavior

Docstrings must not:

- Address the reader directly.
- Use conversational language.
- Include jokes or sarcasm.
- Repeat obvious implementation details.
- Claim behavior that is not enforced by code.
- Hide uncertainty.
- Over-explain trivial private helpers.

Required for:

- Public classes
- Public methods
- Public functions
- Service classes
- Data contract classes
- Persistence classes
- Registry-facing components
- Lifecycle components
- Non-trivial private helpers where intent is not obvious

Not required for:

- Tiny private helpers with obvious behavior
- Simple dataclass containers when fields are self-explanatory
- Test helper functions with clear names

Preferred function docstring style:

    def load_dataset(self, dataset_id: DatasetId) -> pd.DataFrame:
        """
        Load a historical dataset from persistent storage.

        The dataset identifier defines the exchange, market type, symbol, and
        timeframe. The method resolves the dataset path through the configured
        storage policy and validates the loaded frame before returning it.

        Parameters
        ----------
        dataset_id:
            Stable market dataset identifier used to locate the stored OHLCV data.

        Returns
        -------
        pandas.DataFrame
            Validated OHLCV dataframe ordered by timestamp.

        Raises
        ------
        FileNotFoundError
            Raised when the dataset does not exist in storage.
        ValueError
            Raised when the loaded dataset violates the expected OHLCV schema.

        Notes
        -----
        The method does not create missing datasets. Dataset creation is handled by
        the historical download and persistence pipeline.
        """

Preferred class docstring style:

    class HistoricalDatasetService:
        """
        Coordinate access to historical market datasets.

        The service is responsible for resolving dataset identity, loading stored
        OHLCV data, and exposing validated datasets to application and GUI layers.
        It does not own exchange connectivity or user-interface behavior.

        The service is registered during application startup and is expected to be
        resolved through AppContext. Direct construction outside the composition
        root is not part of the supported lifecycle contract.
        """

---

# 9. Contract Rules

Before changing code, identify the relevant contract.

A contract may be:

- Function signature
- Method signature
- Class responsibility
- Module responsibility
- File format
- Data schema
- Lifecycle order
- Service registration rule
- Naming convention
- Persistence convention
- Test expectation
- Public API behavior
- GUI interaction rule
- Threading rule
- Async execution rule
- Error-handling rule

Do not break contracts silently.

If a contract must change:

- State the old contract.
- State the new contract.
- Explain why the change is required.
- Update all affected callers.
- Update tests.
- Update docs if docs exist for that contract.
- Validate that no stale behavior remains.

When uncertain whether something is a contract, treat it as a contract and preserve it.

---

# 10. Error Handling Rules

Codex must follow these error-handling rules:

- Fail clearly.
- Do not hide invalid state.
- Do not replace real errors with vague messages.
- Include useful context in exceptions.
- Validate inputs at system boundaries.
- Do not validate the same thing repeatedly in hot paths unless necessary.
- Do not use broad fallback logic to make broken state appear valid.
- Do not continue after critical initialization failure unless the system explicitly supports degraded mode.
- Do not catch Exception unless the layer is explicitly responsible for boundary-level error reporting.
- Do not use empty except blocks.
- Do not convert exceptions into silent returns.
- Do not log an error and continue unless continuing is safe and intentional.
- Do not remove existing defensive checks unless the task explicitly requires it and validation proves they are redundant.

Good error style:

    raise ValueError(f"Missing required OHLCV columns: {missing}")

Bad error style:

    raise Exception("Something went wrong")

Errors should help identify the broken contract.

---

# 11. Testing Rules

Codex must follow these testing rules:

- Prefer existing tests before creating new ones.
- Add tests when changing behavior.
- Add regression tests for bug fixes when feasible.
- Keep tests focused on behavior, not implementation details.
- Do not weaken tests to make them pass.
- Do not delete failing tests unless they are proven obsolete and explicitly approved.
- Do not mark tests as skipped just to pass validation.
- Do not rewrite unrelated tests.
- Do not change test expectations unless the behavior change is explicitly requested.
- If tests cannot run, explain why and provide manual validation steps.
- A change is not validated just because the code "looks correct."

Relevant tests should be selected based on the changed subsystem.

Suggested full test command:

    python -m pytest tests

Suggested GUI release check:

    python -m pytest tests/test_gui_release_checks.py

Suggested data-manager regression check:

    python -m pytest tests/test_data_manager_regressions.py

Suggested metadata and persistence checks:

    python -m pytest tests/test_artifact_metadata_contract.py
    python -m pytest tests/test_artifact_metadata_naming.py
    python -m pytest tests/test_derived_store_metadata_sidecar.py
    python -m pytest tests/test_ohlcv_store_metadata_sidecar.py

Suggested artifact recipe checks:

    python -m pytest tests/test_artifact_recipe_store.py
    python -m pytest tests/test_artifact_recipe_executor.py
    python -m pytest tests/test_artifact_recipe_collection_store.py

Suggested analysis database checks:

    python -m pytest tests/test_analysis_database_contract.py
    python -m pytest tests/test_analysis_database_store.py
    python -m pytest tests/test_analysis_database_materialization.py
    python -m pytest tests/test_analysis_database_component_editor.py

Codex may run narrower tests first, then broader tests when appropriate.

---

# 12. Dependency Rules

Codex must follow these dependency rules:

- Do not add third-party dependencies without explicit approval.
- Prefer the Python standard library when reasonable.
- Do not upgrade dependencies unless the task requires it.
- Do not edit lock files unless dependency changes are explicitly requested.
- Do not install packages globally.
- Do not modify the user's Python environment without explicit approval.
- Do not change virtual environment configuration unless explicitly requested.
- Do not introduce optional dependencies as a shortcut around project architecture.
- Do not add dependency-specific code without validating that the dependency is available in the project environment.

If a dependency seems necessary, report:

- Dependency name
- Reason it is needed
- Alternative using existing dependencies or standard library
- Impact on installation and deployment
- Required files to update

Wait for explicit approval before modifying dependency files.

---

# 13. File Handling Rules

Codex must follow these file-handling rules:

- Do not edit binary files.
- Do not edit zip archives.
- Do not commit generated caches.
- Do not touch virtual environments.
- Do not modify datasets unless explicitly requested.
- Do not move user data.
- Do not delete files unless the task explicitly requires deletion.
- Do not create backup files inside the repo unless explicitly requested.
- Do not create duplicate "new", "fixed", "final", "v2", or "backup" files unless the task explicitly asks for them.
- Do not edit files outside the repository.
- Do not write temporary files into source directories.
- Do not modify generated artifacts unless generation is the explicit task.
- Do not modify IDE settings unless explicitly requested.

Forbidden file patterns unless explicitly approved:

- *.zip
- *.pyc
- __pycache__/
- .pytest_cache/
- .mypy_cache/
- .ruff_cache/
- .venv/
- venv/
- .env
- *.db
- *.sqlite
- *.log
- local secrets
- API keys
- downloaded datasets
- generated market data

If ignored files appear relevant, report them instead of editing them.

---

# 14. Git Safety Rules

Codex must not run destructive Git commands.

Forbidden unless explicitly approved:

- git push
- git pull
- git reset
- git reset --hard
- git clean
- git checkout -- .
- git restore .
- git restore --source
- git rebase
- git merge
- git commit
- git push --force
- git push --force-with-lease
- git branch -D
- git tag -d
- git remote remove
- git remote set-url

Allowed read-only commands:

- git status
- git diff
- git diff --stat
- git log
- git branch
- git remote -v
- git show
- git ls-files

Codex may suggest Git commands, but the user decides whether to run them.

If Git state matters, Codex must ask the user to run the command or provide the output.

Codex must not attempt to synchronize, pull, push, reset, clean, rebase, or force-update the repository.

---

# 15. Security and Secrets Rules

Codex must follow these security rules:

- Do not print secrets.
- Do not copy secrets into code.
- Do not commit API keys, tokens, passwords, cookies, private URLs, or credentials.
- Do not add secrets to documentation.
- Do not inspect environment files unless the task explicitly requires it.
- Do not modify authentication or credential handling unless explicitly requested.
- Do not weaken validation around credentials.
- Do not add network calls unless the task explicitly requires them.
- Do not send project data outside the repository context.

If a secret is found in a file that appears tracked, report it immediately and do not duplicate it.

---

# 16. Performance Rules

Performance changes must be explicit and validated.

Codex must not optimize code unless performance is part of the task.

When performance is part of the task:

- Identify the hot path.
- Identify the current cost.
- Prefer reducing repeated work before adding complexity.
- Avoid speculative micro-optimizations.
- Avoid changing behavior for speed unless explicitly approved.
- Validate correctness before and after optimization.
- Add or run relevant regression tests.
- Report any tradeoff between performance and readability.

For hot paths:

- Avoid unnecessary copying.
- Avoid repeated full scans when cached or windowed logic is available.
- Avoid repeated object creation inside tight loops.
- Avoid hidden expensive work in properties.
- Avoid broad listener fan-out.
- Avoid layout recalculation when only paint data changed.

Performance fixes must preserve behavior unless the behavior change is explicitly requested.

---

# 17. Layering Rules

Codex must preserve project layering.

General layering principles:

- Lower layers must not depend on higher layers.
- Core logic must not depend on GUI code.
- Persistence logic must not depend on GUI code.
- GUI code may call services through approved bridges or context objects.
- Data contracts must not depend on presentation concerns.
- Test helpers must not leak into production code.
- Runtime services must not be constructed ad hoc when lifecycle registration exists.

If a requested change appears to violate layering, report the risk before editing.

---

# 17.1 No Shared Responsibility Rule

Every responsibility must have one clear owner.

Codex must not duplicate ownership of the same responsibility across multiple modules, layers, services, or GUI components.

A responsibility includes:

- Lifecycle ownership
- Service registration
- Runtime state mutation
- Data loading
- Data persistence
- Metadata validation
- Artifact naming
- Recipe execution
- Financial tool calculation
- GUI presentation
- User interaction
- Chart rendering
- Error routing
- Audit reporting
- Configuration resolution

Rules:

- Do not implement the same responsibility in more than one layer.
- Do not duplicate business logic in GUI code when a data or core service owns it.
- Do not duplicate persistence logic in widgets.
- Do not duplicate configuration resolution across unrelated modules.
- Do not duplicate financial tool calculation logic between chart workflows and data-manager workflows.
- Do not make GUI components responsible for data contracts.
- Do not make data services responsible for GUI behavior.
- Do not make core services responsible for Qt object ownership.
- Do not make compatibility facades own implementation logic.
- Do not create parallel “almost the same” paths for loading, saving, validating, or calculating data.

When shared behavior is needed, Codex must identify the correct owner before editing.

If ownership is unclear, Codex must stop and report:

- The duplicated or unclear responsibility
- The modules currently sharing it
- The likely correct owner
- The safest migration path
- The risks of changing it

Codex must not resolve unclear ownership by adding another helper, fallback, adapter, or service without explicit approval.

Preferred ownership model:

- Core owns lifecycle, AppContext, service registration, runtime state, audit, and error coordination.
- Data services own persistence, metadata, lineage, recipes, recovery, and validation.
- Financial tools own calculation contracts, naming, specs, and deterministic computation.
- GUI owns presentation, user interaction, Qt widgets, chart display, and GUI-thread orchestration.
- Bridge/runner code owns communication between GUI and core threads.
- Tests own verification only and must not introduce production behavior.

If a responsibility appears in multiple places, Codex must treat it as architecture risk unless the duplication is explicitly documented as intentional.

# 18. Leonardo Architecture Rules

Leonardo has a lifecycle-centered architecture.

Codex must preserve these rules:

- LeonardoApp is the composition root.
- LeonardoApp owns application startup and shutdown.
- LeonardoApp creates and completes AppContext during startup.
- AppContext is the shared runtime context after startup.
- Services must be registered centrally through the application lifecycle.
- External systems must not register core services.
- HistoricalDatasetService must be registered by the core application lifecycle.
- GUI code must consume core services through the approved context or bridge layer.
- GUI code must not construct core services directly unless the architecture explicitly allows it.
- The service registry is a central source of runtime services.
- Registry keys must remain stable unless the task explicitly changes the registry contract.
- Startup order matters and must not be changed casually.
- Shutdown behavior must remain safe and idempotent.
- Async lifecycle behavior must not block the GUI thread.

Do not bypass lifecycle rules to make a local error disappear.

A missing service must be fixed at the registration/lifecycle level unless the missing service is intentionally optional.

---

# 19. Leonardo Core Rules

Codex must treat the core package as the application foundation.

Core rules:

- Core owns application lifecycle.
- Core owns AppContext construction.
- Core owns service registration.
- Core owns audit and state coordination.
- Core must not import GUI implementation details.
- Core must remain usable without direct GUI construction.
- Core services must expose clear contracts.
- Core startup must fail clearly when required services cannot be registered.
- Core shutdown must clean up lifecycle services safely.

Files likely related to core lifecycle include:

- src/leonardo/core/app.py
- src/leonardo/core/context.py
- src/leonardo/core/registry_keys.py
- src/leonardo/core/audit.py
- src/leonardo/core/state.py
- src/leonardo/gui/core_runner.py
- src/leonardo/gui/core_bridge.py

Changes to these files require careful audit and validation.

---

# 20. Leonardo Data Manager and Persistence Rules

The Data Manager must preserve data identity, metadata, and lineage.

Core data principles:

- OHLCV is the market-data ground truth.
- CSV files store tabular values.
- JSON sidecars store artifact identity, metadata, parameters, and lineage.
- Filenames are not sufficient as the sole source of truth when sidecar metadata exists.
- Metadata contracts must be validated, not assumed.
- Saved artifacts must have stable identity.
- Derived artifacts must preserve source lineage.
- Analysis databases must define what they contain.
- Recipes must preserve enough information to regenerate artifacts where supported.
- Recovery and regeneration must respect metadata contracts.

Codex must not silently change:

- Dataset identity rules
- Artifact naming rules
- Sidecar schema
- Recipe schema
- Analysis database schema
- Persistence paths
- Recovery behavior
- Regeneration behavior

Files likely related to data manager and persistence include:

- src/leonardo/data/historical/ohlcv/catalog/dataset_service.py
- src/leonardo/data/historical/ohlcv/storage/store_csv.py
- src/leonardo/data/historical/artifacts/storage/derived_csv_store.py
- src/leonardo/data/historical/common/paths.py
- src/leonardo/data/historical/ohlcv/download/downloader.py
- src/leonardo/data/historical/ohlcv/validation/validator.py
- src/leonardo/data/historical/analysis_database/contracts.py
- src/leonardo/data/historical/analysis_database/naming.py
- src/leonardo/data/historical/analysis_database/store.py
- src/leonardo/data/historical/analysis_database/component_editor.py
- src/leonardo/data/historical/artifacts/metadata/contracts.py
- src/leonardo/data/historical/artifacts/metadata/naming.py
- src/leonardo/data/historical/artifacts/metadata/backfill.py
- src/leonardo/data/historical/artifacts/recipes/store.py
- src/leonardo/data/historical/artifacts/recipes/executor.py
- src/leonardo/data/historical/artifacts/recipes/collection_store.py
- src/leonardo/data/historical/artifacts/recovery/planner.py
- src/leonardo/data/historical/artifacts/recovery/regenerator.py
- src/leonardo/data/historical/artifacts/recovery/database_rebuilder.py

When working in this area, validate against the related tests before claiming success.

---

# 21. Leonardo Financial Tools Rules

Financial tools must remain modular and contract-driven.

Financial tools include:

- Indicators
- Oscillators
- Constructs
- Naming runtime
- Specs runtime
- Tool contracts
- Execution context

Rules:

- Each indicator, oscillator, or construct should remain modular.
- Manager modules may orchestrate tools but should not absorb implementation logic.
- Runtime modules must preserve deterministic behavior.
- Naming must remain stable and contract-driven.
- Specs must describe behavior accurately.
- Tool manifests must remain synchronized with runtime behavior.
- Do not change output column naming casually.
- Do not change parameter naming casually.
- Do not change default behavior casually.
- Do not mix indicator, oscillator, and construct responsibilities.
- Do not move implementation into GUI code.
- Do not make persistence depend on tool internals beyond stable contracts.

Files likely related to financial tools include:

- src/leonardo/financial_tools/
- src/leonardo/financial_tools/ft_naming.py
- src/leonardo/financial_tools/ft_specs.py
- src/leonardo/financial_tools/execution_context.py
- src/leonardo/financial_tools/indicators/
- src/leonardo/financial_tools/oscillators/
- src/leonardo/financial_tools/constructs/
- src/leonardo/financial_tools/naming_runtime/
- src/leonardo/financial_tools/specs_runtime/
- src/leonardo/financial_tools/tool_contracts/

When changing financial tools, validate naming, specs, contracts, and related materialization tests.

---

# 22. Leonardo GUI Rules

GUI changes must preserve lifecycle, responsiveness, and chart behavior.

Rules:

- GUI must consume core services through approved context or bridge mechanisms.
- GUI must not register core services externally.
- GUI must not construct lifecycle-owned services directly unless explicitly allowed.
- GUI windows should not own core application lifecycle.
- GUI windows should request services from the context or bridge.
- GUI must avoid blocking the UI thread with long-running work.
- Async work must be routed through approved runner/bridge mechanisms.
- UI changes must preserve existing user workflows unless explicitly changed.
- GUI code should not contain persistence rules that belong in data services.
- GUI code should not contain financial tool implementation logic.

Files likely related to GUI include:

- src/leonardo/gui/app.py
- src/leonardo/gui/main_window.py
- src/leonardo/gui/core_runner.py
- src/leonardo/gui/core_bridge.py
- src/leonardo/gui/windows/
- src/leonardo/gui/chart/
- src/leonardo/gui/historical_chart/

GUI changes require careful validation because import errors, signal changes, and lifecycle changes can break runtime behavior without obvious unit-test failures.

---

# 23. Leonardo Chart and Rendering Rules

Chart rendering is performance-sensitive.

Rules:

- Avoid unnecessary defensive copying in hot render paths unless mutation safety requires it.
- Avoid repeated full visible-window scans during pan, zoom, or crosshair movement.
- Avoid adding new viewport listeners without checking fan-out impact.
- Avoid layout recalculation when only paint data changed.
- Avoid Python loops in hot rendering paths when existing vectorized or cached logic is available.
- Avoid duplicating study refresh logic.
- Avoid duplicating style resolution logic.
- Keep rendering behavior deterministic.
- Preserve chart visual behavior unless the task explicitly changes it.
- Preserve oscillator and overlay behavior unless explicitly changed.
- Preserve right-axis tag behavior unless explicitly changed.
- Preserve viewport contracts unless explicitly changed.

Files likely related to chart rendering include:

- src/leonardo/gui/chart/chart_render.py
- src/leonardo/gui/chart/series_render.py
- src/leonardo/gui/chart/viewport.py
- src/leonardo/gui/chart/workspace.py
- src/leonardo/gui/chart/_workspace/
- src/leonardo/gui/chart/panes/
- src/leonardo/gui/chart/rendering/
- src/leonardo/gui/chart/studies.py
- src/leonardo/gui/chart/study_style_defaults.py
- src/leonardo/gui/chart/study_style_resolver.py

Performance fixes must be validated against behavior.

Do not trade correctness for speed unless explicitly approved.

---

# 24. Leonardo Historical Chart Rules

Historical chart logic bridges data, financial tools, and GUI display.

Rules:

- Historical chart code must not bypass Data Manager contracts.
- Historical chart code must not construct lifecycle-owned services directly.
- Historical chart code must preserve dataset identity.
- Study application must preserve style and projection contracts.
- Tool execution must preserve financial tool contracts.
- Refill policy must preserve chart continuity.
- Projection logic must not mutate source data unexpectedly.
- Session state must remain explicit and inspectable.

Files likely related to historical chart behavior include:

- src/leonardo/gui/historical_chart/
- src/leonardo/gui/historical_chart_controller.py
- src/leonardo/gui/windows/historical_chart_panel.py
- src/leonardo/gui/windows/historical_chart_window.py
- src/leonardo/gui/windows/historical_workspace_widget.py
- src/leonardo/gui/windows/_historical_chart_panel/

Changes in this area must validate imports, service resolution, study application, and chart update behavior.

---

# 25. Leonardo Data Manager GUI Rules

The Data Manager GUI is presentation and orchestration, not persistence truth.

Rules:

- GUI widgets must not redefine persistence contracts.
- GUI widgets must call data services for storage behavior.
- GUI widgets must not treat filenames as authoritative when metadata exists.
- GUI widgets must preserve user selections clearly.
- GUI widgets must not silently discard selected components.
- Preview widgets must not mutate source datasets.
- Build dialogs must preserve recipe and analysis database contracts.
- Metadata tools must surface contract problems clearly.

Files likely related to Data Manager GUI include:

- src/leonardo/gui/windows/data_manager_window.py
- src/leonardo/gui/windows/historical_data_manager_window.py
- src/leonardo/gui/windows/_data_manager/

Changes in this area should validate related data manager tests when they affect persistence or materialization behavior.

---

# 26. Import and Refactor Rules

Refactors must be explicit.

Do not refactor unless the task asks for refactoring.

When refactoring is requested:

- Audit current imports first.
- Identify public import paths.
- Identify test import paths.
- Preserve compatibility where reasonable.
- Avoid moving multiple unrelated systems in one task.
- Update all affected imports.
- Run import and test validation.
- Report any compatibility risks.

Do not rewrite imports across the project unless import rewriting is the task.

Do not create compatibility shims unless explicitly approved or necessary to preserve a public contract.

Do not leave duplicate old and new implementations active unless explicitly requested.

---

# 27. Documentation Update Rules

Documentation updates must match actual behavior.

Rules:

- Do not update documentation to describe behavior that is not implemented.
- Do not change code to match documentation unless the task explicitly requires it.
- Do not rewrite large documentation files for style only.
- Do not remove useful technical detail.
- Do not add conversational comments or jokes to project documentation unless the document is explicitly informal.
- Keep technical documentation precise.
- Update docs when a public contract changes.
- Update docs when file layout or lifecycle rules change.
- Report stale docs when found.

Documentation must not become a museum of lies with headings.

---

# 28. Final Report Format

After each task, Codex must report the result using this structure:

## Audit

- What was inspected
- What was found
- Relevant contracts
- Risk level

## Update

- Files changed
- Summary of changes
- Reason for changes
- Out-of-scope findings left unchanged

## Validation

- Commands run
- Results
- Original-code comparison
- Failures, if any
- Remaining risks

If no files were changed, state:

"No files were changed."

If validation could not be completed, state:

"Validation incomplete."

Then explain:

- What could not be validated
- Why it could not be validated
- What manual validation is required

Do not claim completion when validation is incomplete.

---

# 29. Standard Read-Only Audit Prompt Behavior

When asked to audit, Codex must default to read-only behavior.

Read-only audit means:

- Do not edit files.
- Do not create files.
- Do not delete files.
- Do not run destructive commands.
- Do not run Git write commands.
- Inspect relevant source files.
- Inspect relevant tests.
- Report findings by severity.
- Propose next steps.

Severity levels:

- Critical: likely runtime failure, data loss, broken lifecycle, broken persistence, or security issue.
- High: likely incorrect behavior, broken contract, serious maintainability issue, or test gap around critical behavior.
- Medium: localized bug risk, unclear responsibility, missing validation, or moderate maintainability issue.
- Low: cleanup, naming clarity, minor documentation mismatch, or optional improvement.

Audit reports must separate confirmed issues from suspected issues.

---

# 30. Standard Update Prompt Behavior

When asked to update code, Codex must:

- Begin with a short audit unless the user explicitly provides the exact patch.
- Apply the smallest safe change.
- Avoid unrelated edits.
- Preserve contracts.
- Run relevant validation.
- Report the diff scope.
- Report remaining risks.

If the task is ambiguous, Codex must make the safest narrow interpretation and report assumptions before editing.

If ambiguity could cause destructive or broad changes, Codex must ask for clarification before editing.

---

# 31. Forbidden Behaviors

Codex must not:

- Redesign the application without explicit instruction.
- Replace architecture with a simpler fake architecture.
- Create fake services to satisfy missing dependencies.
- Bypass the service registry to hide lifecycle problems.
- Hide broken state with silent fallbacks.
- Remove validation to make tests pass.
- Weaken tests to make code pass.
- Create duplicate replacement files without approval.
- Run Git write commands.
- Pull from remote.
- Push to remote.
- Force-update Git history.
- Delete large groups of files.
- Install dependencies without approval.
- Modify files outside the repository.
- Edit secrets.
- Edit binary archives.
- Modify datasets unless explicitly requested.
- Claim success without validation.
- Treat warnings as irrelevant without checking whether they affect the requested task.
- Create shared responsibility between layers or duplicate ownership of lifecycle, persistence, calculation, validation, or GUI behavior.

---

# 32. What Done Means

A task is done only when:

- The requested scope was addressed.
- The diff is surgical.
- Relevant contracts were preserved or explicitly updated.
- Relevant tests were run or manual validation was clearly described.
- Original-code comparison found no unrelated changes.
- Failures were reported honestly.
- Remaining risks were documented.
- No forbidden actions were performed.
- The change did not introduce shared ownership of a responsibility across layers.

If these conditions are not met, the task is not complete.
