# Switchboard

Connect the Claude Code harness to non-Anthropic open models via **OpenRouter**, and
switch between Anthropic and OpenRouter models (ideally mid-session).

> **Status:** brainstorming / design. No implementation yet — the technical build
> (routing config, launch scripts, switching mechanism) is gated behind an approved
> design.

## Where things live

- **Tracking docs (system of record):** the Obsidian vault project
  `01 PROJECTS/Switchboard/` (hub note + `_context/`). Decisions, research, plan, and
  issues live there, not here.
- **Code (when built):** this repo.

## Objective

1. Prove an OpenRouter model can drive Claude Code; measure setup complexity.
2. Determine whether existing skills, slash commands, MCP servers, hooks, and
   subagents still work under a non-Claude model (the compatibility matrix).
3. Build an ergonomic model switch (in-session and / or per-session profiles).

## Decided so far

- Routing tool: **claude-code-router (CCR)** — single durable choice (see vault DEC-001).

See the vault project for the full plan and decisions.
