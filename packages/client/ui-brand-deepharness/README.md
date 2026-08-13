# @deepseek-ai/dsh-client-ui-brand-deepharness

English | [中文](README.zh.md)

Deployment-owned client plugin for presenting the web shell as **DeepHarness** without editing upstream UI components. It shadows the versioned internal-testing and official-provider onboarding entries through the existing `settings.onboarding` priority mechanism, then projects the DeepHarness wordmark, DH monogram, document title, favicon, and PWA metadata over the upstream browser chrome. Provider and model identifiers remain unchanged because they are functional API configuration rather than product branding.

The DOM projection recognizes only the upstream wordmark's private clip-path id and the fish mark's exact SVG view box. The effect is reversible and re-applies after React remounts through a scoped `MutationObserver`.

## Model Experience

None. This package changes browser chrome and onboarding composition only; it does not modify prompts, tools, model routing, or provider requests.

#### KV Cache effect

None; no model request content is assembled by this package.
