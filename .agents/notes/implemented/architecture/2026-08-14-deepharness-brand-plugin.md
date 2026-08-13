# DeepHarness branding overlay

## Decision

The deployment brand is a separate browser plugin, `@deepseek-ai/dsh-client-ui-brand-deepharness`. The upstream settings, sidebar, conversation, primitives, and app-shell components remain unchanged.

The internal-testing and official-provider onboarding cells are replaced through the slot registry's existing priority election: the overlay registers the same stable ids at a lower priority and completes them without rendering. This keeps the original plugins installed for their Models settings functionality while removing their first-run product chrome.

The sidebar and empty-state brand locations do not expose brand-specific slots. Until those owners add such a seam, the overlay recognizes only the private DeepSeek wordmark clip id and exact fish SVG view box, marks their immediate hosts, and applies a scoped DeepHarness wordmark or DH monogram. A MutationObserver repeats that projection after React remounts. The same reversible effect owns the document title, favicon, and manifest link.

Provider names, model ids, package names, and API namespaces are deliberately untouched. They identify functional integrations and changing them would break configuration or misrepresent which provider serves a request.

## Consequences

- Removing the overlay row restores upstream branding and onboarding without reverting component code.
- A future upstream brand slot should replace the DOM projection; the onboarding shadow can remain a normal policy plugin.
- Exact marker matching prevents broad text rewriting from changing DeepSeek provider configuration or conversation content.
