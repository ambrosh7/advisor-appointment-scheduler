# CI gates (Phase 8)

## Default gate (chat)

```bash
PYTHONPATH=src pytest -q -m "not voice and not live_mcp"
```

Runs unit + chat integration tests, including MCP failure-injection against **tool doubles** (not live Google).

## Optional — voice

```bash
PYTHONPATH=src pytest -q -m voice
```

Voice adapters are optional in CI; they use in-memory STT/TTS doubles.

## Live Google MCP (credentials required)

```bash
PYTHONPATH=src pytest -q -m live_mcp
```

Skipped automatically when `GoogleMcpConfig.validate_for_live()` reports missing credentials. This remains the integration gate for real Calendar / Docs / Gmail.

## Full local suite

```bash
PYTHONPATH=src pytest -q
```
