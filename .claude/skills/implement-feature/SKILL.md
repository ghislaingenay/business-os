---
name: implement-feature
description: Take a feature from context/features/, move it to "Doing", implement it (or a single phase for multi-PR features) on its own branch against its paired technical design, and verify the result with an independent subagent reviewer. Supports PR decomposition (feat-NNN-a, feat-NNN-b, feat-NNN-c) with progress tracking. Use when the user says "implement FEAT-XXX", "start on FEAT-XXX phase N", "work on <feature name>", or "pick up the next feature".
---

# Implement Feature

Implements a feature (or phase of a feature) end-to-end on its own branch: locate
it, mark it in progress, read its paired technical design, check for PR
decomposition, build it following this repo's workflow (`context/ai-interaction.md`)
and coding standards (`context/coding-standards.md`), then hand the diff to an
independent subagent for verification against the FEAT/TD docs before reporting
back. Tracks progress across multiple PRs when features are decomposed into phases.

## Arguments

`$ARGUMENTS` names the feature — a `FEAT-NNN` id, a filename, or a title fragment
(e.g. `FEAT-000`, `core-identity-data-model`, "core identity"). Optionally include
a phase identifier for multi-PR features (e.g., `FEAT-001 phase 1`, `FEAT-001-a`,
`FEAT-001 PR1`). If empty, ask the user which feature to implement, or list
`context/features/README.md` rows whose Status is `Draft` and ask them to pick one.

## Steps

1. **Resolve the feature file.**
   - Find the matching file in `context/features/FEAT-NNN-*.md`. Confirm the match
     with the user if ambiguous.
   - Read it fully, and read its paired technical design (linked at the top under
     "Technical Design:", also at `context/technical-designs/TD-NNN-*.md`).
   - Check the feature's "Dependencies → Internal" section for `[[FEAT-XXX]]`
     references. If a dependency's status in `context/features/README.md` is not
     `Done`, tell the user and confirm whether to proceed anyway before continuing.

1a. **Check for PR decomposition in the technical design.**

- Look for an "Implementation Phases (PR Mapping)" or similar section in the TD
  that breaks the feature into multiple PRs (e.g., PR1/Phase 1, PR2/Phase 2).
- If found:
  - List all phases with their scope and dependencies to the user
  - Check if any phases are already marked as complete (look for checkboxes or
    "Status: Complete" markers in the TD or a "## PR Progress" section in the
    FEAT file)
  - Ask which phase to implement (e.g., "Phase 1", "PR1", or just "1")
  - If the user doesn't specify, implement the next incomplete phase in sequence
- If not found, proceed with the entire feature as a single implementation.

2. **Mark the feature as Doing (or track PR progress).**
   - **First PR/Phase:**
     - In the feature file itself, change `Status: Draft` to `Status: Doing`
     - Update `Last Updated:` to today's date
     - In `context/features/README.md`, update the Status column to `Doing`
     - Do the same in `context/technical-designs/README.md` and the TD file header
     - If the TD has phases, add a "## PR Progress" section after the header in
       both the FEAT and TD files:

       ```markdown
       ## PR Progress

       - [ ] Phase 1: [brief description] (branch: feat-NNN-a)
       - [ ] Phase 2: [brief description] (branch: feat-NNN-b)
       - [ ] Phase 3: [brief description] (branch: feat-NNN-c)
       ```
   - **Subsequent PRs:**
     - Status remains `Doing`, just update the `Last Updated:` date
     - The "## PR Progress" section already exists from the first PR
   - Populate `context/current-feature.md`: set the title, the `## File` link,
     goals pulled from ONLY the phase's functional requirements (not the entire
     feature), and a short Notes summary indicating which phase is in progress.

3. **Create a branch.**
   - Per `context/ai-interaction.md`, create a feature branch off the current base
     branch before writing code.
   - **Single PR feature**: `feature/<short-slug>` (e.g., `feature/rate-limiting`)
   - **Multi-PR feature**: `feature/<short-slug>-<phase>` where phase is a letter
     (e.g., `feature/hybrid-upload-a`, `feature/hybrid-upload-b`)
     - Phase 1/PR1 → `-a`, Phase 2/PR2 → `-b`, Phase 3/PR3 → `-c`, etc.
   - Confirm the branch name with the user if the feature title doesn't map cleanly
     to a slug or if phase identification is ambiguous.

4. **Implement against the technical design**, not just the feature doc — the TD
   is the source of truth for schema, components, API shape, and sequencing:
   - **If implementing a specific phase**: Follow ONLY the scope defined in that
     phase's section in the TD's "Implementation Phases" area. Do NOT implement
     items from other phases. Respect dependencies listed in the phase description
     (e.g., "Depends on: Phase 1 merged, FEAT-003 storage interface available").
   - **If implementing the complete feature**: Follow the entire TD.
   - Follow the TD's "New Components" / "Modified Components" and "Data Model"
     sections exactly (table names, column types, constraints, indexes).
   - Respect migration ordering called out in the TD's "Dependencies" or
     "Sequence Flow" sections (e.g. TD-000 requires TD-002's `roles` table to
     exist before the `users` migration runs).
   - Match existing project layout: `cmd/` entrypoints, `internal/` core logic,
     migrations via Goose, config in `config/`.
   - Implement every Acceptance Criteria checkbox under each FR that is part of
     this phase's scope — these define "done," not just the prose description.
     For multi-phase features, implement only the ACs that correspond to
     functionality delivered in this phase.
   - Do not implement anything listed under the feature's "Non-Goals" section.
   - Make minimal, focused changes. Don't refactor unrelated code and don't add
     functionality beyond the FRs and their acceptance criteria (or the current
     phase's scope for multi-phase features).

   Follow `context/coding-standards.md` in full, not just Clean Architecture
   layering — check each of these explicitly before considering a file done:
   - **Package organization**: organize by business domain (`internal/tenant/`,
     `internal/apikey/`), not by technical layer (`internal/handlers/`,
     `internal/services/`). Never add to or create generic `models`, `utils`,
     `helpers`, or `common` packages. A new domain package gets the standard
     shape: `model.go`, `dto.go`, `repository.go`, `service.go`, `handler.go`,
     `errors.go`.
   - **Models vs DTOs**: domain models live in the owning package and are never
     returned directly from handlers. Request/response types are separate DTOs
     in `dto.go` with their own `json`/`validate` tags — never expose a DB
     entity through an API response.
   - **Validation**: `validate` tags go on DTOs/domain models; any custom
     validator implementation belongs in `internal/validation/`, registered
     centrally at startup, not inline in a handler. Handlers validate input
     before calling a service — services must not re-parse raw request bodies.
   - **Errors**: define sentinel errors (`var ErrXNotFound = errors.New(...)`)
     or custom error structs in the owning package's `errors.go`, never a
     global errors package. Wrap with `fmt.Errorf("context: %w", err)` at every
     boundary crossing; callers branch with `errors.Is`/`errors.As`. Never
     panic for expected failure paths.
   - **Constructors and startup**: constructors return `(T, error)`, not a bare
     value plus a panic. Only use `panic` for unrecoverable startup failure or
     programmer error, and only in functions explicitly prefixed `Must`
     (`MustLoadConfig`, `MustConnectDatabase`) — never in request-path code.
   - **Migrations**: never call migrations from production server startup
     (`database.Migrate(db)` inside `cmd/server`). Migrations run as a separate
     job/command (`cmd/migrate`); automatic migration-on-boot is acceptable
     only behind a local-development-only flag.
   - **Dependency injection**: interfaces are declared next to the consumer
     that needs them (e.g. `TenantRepository` interface lives in the service
     package, not the repository package), sized to just the methods that
     consumer calls. Wire dependencies via constructor injection
     (`NewService(repo TenantRepository, logger Logger) *Service`) — no service
     locators, no package-level globals.
   - **Layer boundaries**: handlers only parse/validate/call-service/respond —
     no business logic, no DB access, no external calls in a handler. Services
     hold business rules and orchestrate repositories; they must not contain
     HTTP concerns (`http.Request`, status codes). Repositories only do
     persistence and return domain entities — no business rules in SQL-adjacent
     code.
   - **Go idioms and net/http**: use Go 1.22+ `net/http.ServeMux` routing with
     method+pattern registration; explicit method handling per verb; context
     propagation (`context.Context` as first param) through service and
     repository calls for cancellation/deadlines; guard any shared mutable
     state with a mutex or channel rather than reaching for global state;
     `defer` resource cleanup (rows, tx, file handles) right after acquisition.
   - Leave no `TODO`, placeholder, or stubbed branch in the implementation —
     every code path the AC/TD requires must be real.

5. **Test.**
   - Run `gofmt -l .` (or `goimports -l .`) and fix any unformatted files, then
     `go vet ./...` and `go build ./...`; fix all errors before proceeding. Run
     `golangci-lint run` if the repo has it configured.
   - Run `go test ./...` for the affected packages. Add table-driven tests,
     run with `t.Parallel()` where the test is independent, covering the
     feature's "Edge Cases" section and every exported function touched.
   - Confirm mocks for external interfaces (repositories, clients) are used in
     service-layer unit tests instead of hitting real infrastructure; keep
     slower integration tests separate per `context/coding-standards.md`.
   - If the feature touches an HTTP surface, verify it manually (e.g. `curl`)
     per `context/ai-interaction.md`'s workflow before declaring it done.

6. **Verify by invoking the `review-technical-design` skill before declaring
   anything done — do not write your own ad-hoc verification prompt here.**
   - Call the Skill tool with `skill: review-technical-design` and
     `args: <the same feature id/slug you resolved in step 1>`.
   - That skill is the single source of truth for verification: it reads the
     FEAT/TD docs itself, diffs against the base branch, checks data model
     fidelity, API contract, acceptance criteria, business rules/edge cases,
     non-goals, security mitigations, coding standards, and runs
     `go build`/`go vet`/`go test` — then reports a severity-ranked list
     (Blocking / Should-fix / Note) with file:line evidence.
   - Run it as its own step, not folded into your implementation context —
     treat its findings the same way you would an independent subagent's:
     don't self-certify, and don't let your own read of the diff override it.
   - **Stop it short of closeout.** `review-technical-design`'s step 7 (setting
     Status to `Done` and resetting `context/current-feature.md`) is out of
     scope here — this skill owns the Doing→Done handoff to the user (see
     step 7 below). When invoking it mid-implementation, tell it explicitly:
     only run its verification and reporting steps (1–6); do not close out the
     feature.
   - If it reports Blocking findings, fix them and re-invoke the skill before
     continuing — a fresh, independent verification pass is the check, not
     your own judgment that the fix is correct.

7. **Update checkboxes and status once the subagent verification is clean.**
   - **Phase completion (multi-PR features)**:
     - Check off the completed phase in the "## PR Progress" section of both the
       FEAT and TD files (e.g., `- [x] Phase 1: Upload Foundation (feat-001-a)`)
     - Check off ONLY the Acceptance Criteria boxes in the feature file that
       correspond to this phase's scope
     - Check off each goal in `context/current-feature.md` for this phase
     - Update `Last Updated:` date in both FEAT and TD files
     - If ALL phases are complete (all boxes in "## PR Progress" are checked):
       - Change Status to `Review` (not `Done` — user confirms)
       - Add a completion note in the FEAT file after the PR Progress section
     - If more phases remain:
       - Keep Status as `Doing`
       - Clear `context/current-feature.md` content (set back to template state)
   - **Single-PR feature completion**:
     - Check off each satisfied Acceptance Criteria box in the feature file
     - Check off each goal in `context/current-feature.md`
     - Keep Status as `Doing` (user will change to `Done`/`Review`)
   - Report to the user:
     - What was implemented (phase scope or full feature)
     - The `review-technical-design` findings (including Should-fix/Note items)
     - Any Open Questions from the TD that need human decisions
     - For multi-PR: Progress summary (e.g., "Phase 1 of 3 complete, Phase 2 next")
   - Let the user confirm completion and flip status to `Done` themselves.
   - `review-technical-design` checks spec fidelity (does the code match the
     TD/FEAT), not general code quality. In the same report, suggest the user
     run `/code-review` if they also want a correctness/simplification/
     efficiency pass — don't run it automatically here.

8. **Do not commit or merge without explicit permission** — `context/ai-interaction.md`
   requires asking first, and commits must use conventional prefixes restricted to
   `feat:, fix:, chore:, build:, config:, style:` with no AI attribution footer.

## Notes

- **PR decomposition**: Large features should be broken into phases in the TD's
  "Implementation Phases (PR Mapping)" section. Each phase gets its own branch
  (`feat-NNN-a`, `feat-NNN-b`) and PR. Track progress in both FEAT and TD files
  with a "## PR Progress" checklist. Only mark the feature as complete when ALL
  phases are done. Between phases, reset `context/current-feature.md` to empty.
- **Phase dependencies**: Always check phase dependencies before starting (e.g.,
  "Depends on: Phase 1 merged"). If a prerequisite phase isn't complete, stop
  and tell the user rather than proceeding out of order.
- **Acceptance criteria mapping**: For multi-phase features, map each AC to the
  phase that implements it. Only check off ACs that are completed in the current
  phase — leave others unchecked until their phase is done.
- If the technical design has unresolved "Open Questions" that block a design
  decision (e.g. TD-000's cascade-vs-restrict question), stop and ask the user
  before implementing that part rather than guessing.
- If something isn't working after 2-3 attempts, stop and explain rather than
  continuing to try random fixes, per `context/ai-interaction.md`.
