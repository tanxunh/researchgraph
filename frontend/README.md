# ResearchGraph frontend

React 18, Vite, Ant Design. Workspaces: Overview, Library, Document Detail/Versions,
Jobs, Search, Ask and Research. Shared Evidence views resolve immutable locators.

## Development

```sh
npm ci
npm run dev
npm test -- --run
npm run build
```

Development API target: http://127.0.0.1:8000. Production Compose uses
VITE_API_BASE_URL=/ with nginx proxying /api and /health and supporting route refresh.
See [deployment](../docs/deployment.md). Never put API keys in frontend assets.

Evidence uses a desktop side panel and a Drawer below 1200px. Metadata wraps;
comparison tables scroll locally. Search scope revalidates on entry/focus.
Ranked evidence may not directly answer a query. Citation validation checks
structure/references, not semantic entailment.

Final Browser Product Gate: PASS (owner-confirmed). Screenshots: DEFERRED / OPTIONAL.
Frozen frontend baseline: 134 tests. Tests do not replace manual browser review.
See [product overview](../README.md). Screenshots are optional.
