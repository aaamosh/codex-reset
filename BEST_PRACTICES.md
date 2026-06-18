schema: projects_best_practices.v1
last_reviewed_local: "2026-06-18"
consumer: agent_or_tool
human_reader_default: false

records:
  - id: BP-2026-06-18-001
    scope: codex-reset browser companion
    trigger: Codex Reset should become the durable Codex user-helper project while invite-related help remains a temporary overlapping feature
    guardrail: keep the browser companion as a standalone inspectable HTML file with no backend, no storage, no token/cookie/auth-file reads, and no OpenAI endpoint calls; CLI remains the only surface that reads auth and performs reset mutations
    validation:
      - codex-reset.html
      - test_codex_reset_page.py
      - python3 -m unittest
      - agent-isolated-browser acceptance
    fitness_metric: future Codex helper features can be added under Codex Reset without moving secrets or mutations into the static browser page
