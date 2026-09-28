# Codex-callable Jev: proposed system architecture

**Status:** design proposal. The repository currently provides a Python browser agent and a local inspector. It does not yet provide an MCP server, durable jobs, a general decision adapter, or the job tools described here. Preserve the existing `page -> indexed elements -> operation + target -> execution` loop while adding orchestration around it.

## Responsibilities

| Component | Responsibility |
| --- | --- |
| User | Gives Codex a natural-language outcome and any constraints. Resolves account challenges and authorizes consequential actions when required. |
| Codex | Interprets the request, selects available tools, supplies success criteria, reviews evidence and unresolved questions, and reports the verified result. It may use a cheaper subagent for bounded analysis. |
| Jev MCP server | Exposes capabilities and job operations, validates input, persists state, and returns compact progress and evidence references. |
| Job worker | Expands explicit lists and rules into bounded tasks, selects an installed capability, applies budgets, records observations and outcomes, and stops at handoff points. |
| Capability adapters | Perform specific work. The first adapter wraps the existing browser agent; later adapters can handle local files, structured APIs, or finite-choice decisions without a browser. |
| Verifiers | Independently check outcomes against job-specific criteria and attach evidence. A worker's `DONE` choice is only a signal to verify. |

Codex may call another tool directly when it has a more reliable or simpler path. Jev is useful when a bounded, repeatable task can run while Codex waits for a result or a meaningful handoff. The system optimizes for correct, attributable results first, then latency and cost. Unsupported work must remain explicit rather than be claimed as complete.

## Tool contract (proposed)

Expose a local MCP server with structured input and output. The names below are a draft interface to implement and test; they are not callable today.

| Tool | Input | Output |
| --- | --- | --- |
| `get_capabilities()` | None | Installed adapters, supported operations, limits, and input requirements. |
| `submit_job(spec)` | `JobSpec` | `job_id`, accepted specification, initial status. Repeated submission with the same caller-supplied idempotency key returns the same job. |
| `wait_job(job_id)` | Job ID and optional bounded wait duration | Latest status, progress counts, a concise result or handoff, and evidence references. A timeout means the job is still running. |
| `get_evidence(job_id, refs)` | Job ID and evidence IDs | Source metadata and permitted excerpts or artifacts for review. |
| `resume_job(job_id, response)` | Job ID, handoff ID, and answer | Updated status. The handoff ID prevents an old response from resuming a different question. |

`JobSpec` should contain a `goal`, explicit inputs such as item lists and starting URLs when known, output shape, success criteria, limits, and an optional idempotency key. Preserve the user's goal as the browser agent's single natural-language goal; job-level decomposition must not turn into site-specific action scripts or prepared field values. Validate types, URLs, size limits, and permissions before enqueueing. Do not place credentials in job specifications or evidence.

`JobResult` should separate `verified`, `unverified`, and `not_found` data. Each factual value should carry its source URL or local artifact ID, capture time, evidence reference, and verification result. The final job status `completed` means the specified success criteria passed; partial or unverifiable data may be included only when those criteria explicitly permit it. Otherwise return a handoff or failure with the partial results. For example, an unobserved product price is `not_found` with a reason, not a guessed price.

## Job lifecycle and persistence

Use `queued -> running -> completed` for a verified normal path. A running job can move to `needs_reasoning` when evidence requires judgment beyond a bounded choice, or `needs_user` for an account challenge or user decision. Both pause until `resume_job` supplies the matching handoff answer. `blocked` is a terminal capability or site limitation; `failed` is a terminal execution or verification error. Store per-item outcomes as they finish so a partial batch is visible without being mistaken for total success.

Persist the job specification, status transitions, item checkpoints, provenance, handoff IDs, and error summaries in local SQLite transactions. Store larger artifacts outside the database under an ignored local artifact directory, with database references and retention limits. On restart, reconcile jobs left `running`: completed read-only items may resume from checkpoints; any browser mutation with an uncertain result must pause for fresh observation or human review. Do not replay a click, text insertion, selection, booking, purchase, or other mutation just because a worker lost its connection. Record an attempted browser execution before observing its outcome, matching the current agent rule.

Serialize work that controls the same Chrome profile or tab. Different independent, read-only tasks may be parallelized only when their adapters and state are isolated. A job's idempotency key prevents duplicate submission; item checkpoints prevent duplicate expansion. Neither key proves that a browser mutation is safe to retry.

## Execution and verification

1. Codex asks for capabilities and submits a goal, available structured inputs, and observable success criteria.
2. The server validates and queues the job. Code expands explicit item lists, source lists, and fixed rules. It does not call a model just to enumerate known combinations.
3. The worker routes each unit to an installed adapter. For browser work, the adapter starts from an allowed URL and runs the existing indexed-element loop: one TypeSafe request chooses an operation and operation-specific target; only the chosen target head is consumed. `TYPE_TEXT` alone calls the text helper. Targets must match observed elements and supported operations. Model output cannot supply selectors or executable code.
4. The worker records observations, actions, source identifiers, and costs. The browser adapter retains existing freshness and occlusion checks, action and decision budgets, and no-mutation-retry behavior. Screenshots remain optional evidence rather than model input.
5. A verifier checks the actual resulting page or output artifact separately from the adapter's completion signal. It records what passed, what failed, and what could not be established.
6. `wait_job` returns a compact result or a specific handoff. Codex inspects evidence when needed, provides a reasoned answer through `resume_job`, asks the user only where necessary, or reports the verified outcome.

For non-UI finite-choice work, a future adapter can present code-owned options and observed context to a bounded decision model, then validate the chosen option before executing it. Deterministic parsing and rules should handle deterministic cases. This adapter must not turn model text into commands. File, PDF, and API adapters require their own input limits, provenance, and verifiers; they do not inherit browser reliability claims.

`needs_reasoning` should include a concise question, the admissible options if finite, evidence references, and the effect of each answer. `needs_user` should state the exact action or information required and preserve the job checkpoint. A Codex subagent can analyze a batch of `needs_reasoning` items, but Jev cannot silently draw on the user's Codex subscription as its own backend. The current TypeSafe and text-helper calls use configured API credentials and may incur charges.

## Stack and delivery order

Keep Python 3.12+, `uv`, Browser Harness, TypeSafe, and the existing text helper. Add the Python MCP SDK for a local Streamable HTTP server and use Python's `sqlite3` for the first durable queue. Run that service and one worker as a long-lived local process independent of the Codex chat, so a submitted job can continue while Codex is not polling; reconcile queued and interrupted jobs after service restart. The first release can start the service explicitly; automatic startup is a separate convenience feature. Bind only to loopback and require a local credential for MCP calls. Avoid Redis, Celery, or cloud infrastructure until measured concurrency or remote deployment needs justify them. Credentials remain server-side in environment configuration; the MCP server and inspector should remain local-only by default.

1. Define versioned `JobSpec`, `JobResult`, evidence, and handoff schemas with offline contract tests.
2. Add local MCP capability discovery, submission, waiting, evidence retrieval, and resumption; validate limits and persist jobs.
3. Wrap the current browser agent as the first adapter without changing its action policy. Add a verifier for one end-to-end research/export task and test partial results, restart recovery, and uncertain mutations.
4. Add deterministic batch expansion and a finite-choice non-UI adapter. Measure accuracy, time, API calls, and cost on representative tasks before adding more adapters.
5. Extend to new surfaces one at a time, each with explicit capability claims and independent verification. Consequential workflows such as booking or purchase require their own review and user handoff design.

The existing flight, Wikipedia, and local hotel demonstrations establish limited browser behavior, not general website reliability or a working secretary tool. The architecture above is a path to broader use cases with measurable evidence at each stage.
