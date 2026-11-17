# Implementation plan (RFC milestone M1, smallest complete slice)

1. **Discovery:** read upperbody-sw, platform-sw, interfaces, ui and the roadmap. Write down what exists and what needs an adapter (`docs/discovery.md`).
2. **Contracts:** Pydantic models are the source of truth. They are exported to JSON Schema and TypeScript, and a test fails if the exports drift.
3. **Deterministic engine:** a pure function from snapshot and time to a `ReadinessEvaluation`, using the READY, BLOCKED, UNKNOWN and ERROR rules from RFC A.1 and the evidence record from A.2.
4. **Fixtures:** six labelled scenarios. Each is the healthy baseline plus one documented change.
5. **API and evidence:**
   - FastAPI, with SQLite behind Alembic.
   - Live source with reconnect, and fixture source.
   - Bounded WebSocket and structured errors.
6. **Copilot:** an intent router over read-only tools, with refusal before any tool. Ollama and Strands are optional, with a checked rephrase only.
7. **ROS adapter:** an `rclpy` node behind an allowlist, with an HTTP endpoint from the stdlib only, in a separate process.
8. **Web:** four views wired to the API only, with no silent fallback.
9. **Tests:**
   - pytest for classification, freshness, failures, API contracts and read-only enforcement.
   - Vitest for the frontend units.
   - Playwright for the end-to-end run, which also produces the screenshots.
   - An opt-in live ROS check.

**Out of scope** (RFC M2–M4): typed action skills, teleop capture, LeRobot export, policy evaluation and deployment. No upstream repository is changed.
