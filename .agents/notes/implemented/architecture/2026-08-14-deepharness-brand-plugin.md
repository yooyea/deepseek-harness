# Agent Note: DeepHarness branding stays in a client overlay

Status: implemented

English | [中文](2026-08-14-deepharness-brand-plugin.zh.md)

## Problem

The deployment needs DeepHarness product identity and must hide the upstream internal-testing notice and DeepSeek product marks. Editing the upstream settings, sidebar, conversation, primitives, and app-shell components would create a long-lived merge burden and contradict the repository's plugin ownership model.

The onboarding cells have stable slot seams, but the sidebar and empty state do not expose brand-specific slots. The deployment therefore needs a reversible overlay that uses public extension points where they exist and limits DOM projection to exact private markers elsewhere.

## Decision

The deployment brand is a separate browser plugin, `@deepseek-ai/dsh-client-ui-brand-deepharness`. The upstream settings, sidebar, conversation, primitives, and app-shell components remain unchanged.

The internal-testing and official-provider onboarding cells are replaced through the slot registry's existing priority election: the overlay registers the same stable ids at a lower priority and completes them without rendering. This keeps the original plugins installed for their Models settings functionality while removing their first-run product chrome.

The sidebar and empty-state brand locations do not expose brand-specific slots. The overlay recognizes only the private DeepSeek wordmark clip id and exact fish SVG view box, marks their immediate hosts, and applies a scoped DeepHarness wordmark or DH monogram. A `MutationObserver` repeats that projection after React remounts. The same reversible effect owns the document title, favicon, and manifest link.

Provider names, model ids, package names, and API namespaces remain unchanged because they identify functional integrations.

## Alternatives considered

- **Edit upstream React components**: rejected because every upstream update would carry deployment-only conflicts and reverting the brand would require source restoration.
- **Perform broad text and SVG replacement in the built bundle**: rejected because it could alter provider configuration, conversation content, or unrelated icons.
- **Wait for upstream brand slots everywhere**: rejected because the existing deployment needs branding now; exact marker matching keeps the temporary DOM projection narrow and replaceable.

## Consequences

- Removing the overlay row restores upstream branding and onboarding without reverting component code.
- Exact marker matching prevents broad text rewriting from changing DeepSeek provider configuration or conversation content.
- A future upstream brand slot should replace the DOM projection; the onboarding shadow can remain a normal policy plugin.
- Private marker changes can temporarily reveal upstream marks until the overlay is updated, so deployed browser smoke checks remain necessary after upstream upgrades.
