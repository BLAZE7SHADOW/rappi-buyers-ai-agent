# Purchasing Workbench frontend

React and TypeScript interface for the AI Purchasing Agent. The full project setup,
architecture, evaluation and demo instructions live in the repository
[README](../README.md).

## Commands

Requires Node 22.12+.

```bash
npm ci
npm run dev      # http://localhost:5173; /api is proxied to localhost:8000
npm test
npm run lint
npm run build
```

The case page polls while an agent run is active. `AgentProgress.tsx` builds the
buyer-facing investigation path exclusively from persisted tool-call events; it does
not define an expected sequence. Raw events remain available in the collapsed
technical audit log.
