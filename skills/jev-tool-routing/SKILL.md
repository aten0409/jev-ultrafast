---
name: jev-tool-routing
description: Route suitable repeatable multi-step browser or UI workflows to the Jev Ultrafast MCP tool when it is installed and healthy; otherwise choose an available method based on correctness, evidence, latency, and cost.
---

# Jev tool routing

Use this skill when deciding whether Codex should delegate a repeatable workflow to Jev Ultrafast. Jev's current repository contains a browser automation demo and Python library; it does not yet provide the MCP job tools described here. Treat those tools as future capabilities. Call Jev only when its `get_capabilities` tool is available and reports the service installed and healthy. If it is unavailable, unhealthy, or does not support the needed capability, choose another suitable method.

## Choose the execution path

Prioritize correctness and independently checkable evidence, then latency and cost. Do not route every task through Jev.

- Use a direct MCP integration, structured API, or deterministic code when it is suitable and provides reliable results with less overhead.
- Use Jev for repeatable, delegated, multi-step workflows that interact with browser pages or UI and can return evidence for verification.
- Keep open-ended research, multimodal interpretation, and broad synthesis in Codex unless Jev explicitly supports the task and can provide adequate evidence.
- Use TypeSafe or another bounded decision model inside Jev only for a generic, constrained choice that cannot be handled reliably with deterministic rules. Use it only when verified to be cost-effective. Never treat model output as a selector, executable code, or proof of completion.
- If no suitable method can meet the required accuracy, explain the limitation rather than guessing or claiming success.

Respect the user's authorization boundaries. A request to prepare, inspect, or compare does not authorize a purchase, booking, submission, deletion, or other consequential action. Stop at a confirmation boundary when the requested action requires authorization that has not been given.

## Jev job contract

Read the installed tool descriptions and schemas; they are authoritative. Prefer a structured job specification with the user's goal and only the relevant known inputs, such as item lists, source URLs, requested fields, success criteria, and time or model-call limits. Do not invent missing values. For repeated work, provide explicit items and rules so Jev can expand deterministic subjobs without asking a model to rediscover the work structure.

1. Call `get_capabilities()` and confirm Jev is installed, healthy, and supports this job.
2. Submit one `submit_job(spec)` request. Record the returned `job_id` and requested result shape.
3. Call `wait_job(job_id)` according to its documented wait behavior. Continue only while the job is running; avoid tight polling.
4. Read `get_evidence(job_id, refs)` for result fields and their supporting evidence. Check sources, observations, and validation status. Independently verify the actual requested outcome when possible; a `DONE` status alone is insufficient.
5. If the job returns `needs_reasoning`, inspect its evidence and unresolved decision. Resolve the reasoning in Codex, then use `resume_job(job_id, response)` if the tool contract permits. Do not ask Jev to repeat settled reasoning.
6. If it returns `needs_user`, ask only for the specific missing input or authorization, then resume with the user's response. Never infer consent.
7. If it returns `blocked`, report the blocker and useful evidence. This job is terminal; start a new job only after the underlying condition changes. Do not retry mutations or loop on an unchanged failure.

Treat each field as a value plus provenance where available: source URL, observed evidence, timestamp, and validation status. Distinguish verified values, uncertain values, and not-found results. Do not fill gaps by guessing. Report partial results as partial, and surface failures or unsupported capability rather than presenting an incomplete job as successful.
