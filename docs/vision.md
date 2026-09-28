# Vision: a reliable local delegate for Codex

Jev Ultrafast should become a tool that Codex can give a complete, bounded task to, then leave to work until it has a verified result or a specific reason to hand control back. The first capability is browser work; the intended scope is routine assistant work across the browser, local files, and other suitable integrations. Correctness comes first. Speed and API cost matter after the result can be checked.

## Where the project stands

Today this repository contains a browser agent and local inspector. One natural-language goal drives a loop of observed page elements, TypeSafe operation and target choices, and guarded browser execution. It does not yet expose an MCP job tool, durable queue, general extraction pipeline, or non-browser capabilities. The proposed system in [system-architecture.md](system-architecture.md) extends this agent instead of replacing its action loop.

## Roles

| Participant | Responsibility |
| --- | --- |
| User | States the outcome and supplies login, missing facts, or approval when actually required. |
| Codex | Interprets the request, chooses the best available tool, supplies success criteria, handles open-ended reasoning or images when useful, and checks the final result. It can use another connector directly when that is a better fit. |
| Jev Ultrafast tool | Accepts a bounded job, expands explicit lists into work items, executes supported operations, records evidence, verifies what it can, and returns a compact result or a precise handoff. |
| TypeSafe Jev | Makes bounded choices over code-defined candidates when deterministic rules are insufficient, including browser actions and, later, selected non-browser decisions. It is not the source of arbitrary prose or unverified facts. |

Codex should not supervise every click. The tool should not spend a model call on a decision that code can make reliably. It should return `needs_reasoning` with the relevant evidence when interpretation or synthesis needs Codex, and `needs_user` when the user must provide information or act. A long job must expose its status so Codex can wait without repeating browser mutations.

## What “done” means

A job is complete only when its stated success criteria have been checked against evidence independent of an agent's `DONE` choice. Each extracted value should carry its source URL, observation time, and a supporting text span or image reference. An unavailable or uncertain value remains explicitly unknown with a reason. For actions such as booking, purchasing, or sending, the record should distinguish preparation from an externally committed result and stop at a user decision when authorization is still needed.

The tool should preserve completed work after interruption, avoid duplicate external actions, and report partial progress honestly. A compact result should let Codex deliver the answer or inspect only the disputed evidence; full traces stay local and are fetched on demand.

## First proof, then expansion

The first end-to-end proof is a multi-item product collection job, such as Shopee and Lazada listings with specified columns and an Excel output. It exercises browser navigation, authenticated state, structured reading, evidence, missing values, verification, and export. Its work items come from the submitted list or an explicit discovery rule; no website-specific sequence or prepared product values belong in the browser policy.

Further capabilities can handle reservations, price monitoring, local-file operations, and connected services through adapters with the same job and evidence contract. Adding an adapter does not imply that every site or task is supported. Capabilities must be advertised accurately, and unsupported requests must be handed back before a misleading success result.

Measure end-to-end task success, field-level accuracy and provenance, user interventions, elapsed time, Codex work, and paid API usage on representative jobs. Routing and model choices should change only when those measurements show a practical improvement.
