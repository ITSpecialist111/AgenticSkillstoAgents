---
name: Skills Registry
description: Discover what capabilities exist in this org's skills registry — and the MCP bindings needed to call them.
license: MIT
metadata:
  owner: ITSpecialist111
  source: https://github.com/ITSpecialist111/AgenticSkillstoAgents
  readOnly: true
---

# Skills Registry skill

## What this skill does

This skill gives the agent **read-only discovery** over the organisation's
skills registry. The registry is the missing-middle layer between
GitHub-tracked capability manifests and the live MCP servers that execute
each skill. Use it before invoking any business workflow — it answers:

- *"Who in this org can do X?"* (e.g. extract fields from an invoice)
- *"What categories of work are available?"*
- *"Is this skill safe to use for the task in front of me?"*

The skill does **not** execute business logic. Each result includes an
`mcp` binding (server name, tool name, transport) that the agent uses to
call the underlying skill server directly.

## When to use it

Use this skill **first** whenever a user request maps to a likely
capability (invoice processing, PO matching, AP intake, etc.) but you
don't already know which concrete tool to call. Typical signals:

- The user names a business document, process, or system.
- The user asks "can you …?" about something outside the agent's built-in
  toolkit.
- A previous tool call returned a result that needs further enrichment
  ("now reconcile this against the PO").

## Tools

| Tool | When to call |
|---|---|
| `find_skill_by_capability(tag)` | You know roughly what capability you need. Pass a dotted lowercase tag (e.g. `invoice.extract`). |
| `describe_skill(skill_id)` | You have a candidate skill id and need the full manifest (governance, scoring, preconditions, effects) before deciding to call it. |
| `list_capabilities()` | You want the full inventory before forming a plan, or to confirm a tag exists. |

## Typical workflow

1. User: *"Pull the invoice fields out of this PDF and reconcile against the PO."*
2. Agent → `list_capabilities()` to see what tags exist.
3. Agent → `find_skill_by_capability(tag="invoice.extract")`
   - returns `finance/invoice-extract` + its `mcp` binding.
4. Agent → `describe_skill("finance/invoice-extract")` to confirm the
   skill's data classification is acceptable for the user's document.
5. Agent calls the underlying skill server via the returned `mcp` binding.
6. Agent → `find_skill_by_capability(tag="po.match")` and repeats for
   the matching step.
7. Agent composes the final answer.

## What this skill is not

- **Not an executor.** It returns bindings, not results.
- **Not write-enabled.** New skills land via GitHub PR (the
  registry's Stage 1 Register gate), not via this connector.
- **Not authoritative for credentials.** Auth lives on each underlying
  skill server.
