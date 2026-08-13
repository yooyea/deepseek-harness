// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { SkipOnboarding } from '../src/client/SkipOnboarding.tsx'
import { installDeepHarnessBranding } from '../src/client/branding.ts'

afterEach(() => {
  cleanup()
  document.head.innerHTML = ''
  document.body.innerHTML = ''
})

describe('DeepHarness branding projection', () => {
  it('replaces only the product chrome and restores it on teardown', async () => {
    document.head.innerHTML = '<title>Session — DeepSeek Harness</title><link rel="icon" href="/favicon.svg"><link rel="manifest" href="/manifest.webmanifest">'
    document.body.innerHTML = '<button id="brand"><svg><defs><clipPath id="dsh-wordmark-whale-clip"></clipPath></defs></svg></button><span id="hero"><svg viewBox="0 0 23.16 17.04"></svg></span><p>DeepSeek provider</p>'

    const dispose = installDeepHarnessBranding(document)

    expect(document.title).toBe('Session — DeepHarness')
    expect(document.querySelector('#brand')?.hasAttribute('data-deepharness-wordmark')).toBe(true)
    expect(document.querySelector('#hero')?.hasAttribute('data-deepharness-mark')).toBe(true)
    expect(document.body.textContent).toContain('DeepSeek provider')
    expect(document.querySelector<HTMLLinkElement>('link[rel="icon"]')!.href).toContain('data:image/svg+xml')
    expect(document.querySelector<HTMLLinkElement>('link[rel="manifest"]')!.href).toContain('data:application/manifest+json')

    document.title = 'Later — DeepSeek Harness'
    await waitFor(() => { expect(document.title).toBe('Later — DeepHarness') })

    dispose()
    expect(document.title).toBe('Session — DeepSeek Harness')
    expect(document.querySelector('#brand')?.hasAttribute('data-deepharness-wordmark')).toBe(false)
    expect(document.querySelector<HTMLLinkElement>('link[rel="icon"]')!.getAttribute('href')).toBe('/favicon.svg')
  })

  it('completes a shadowed onboarding step once', () => {
    const complete = vi.fn()
    const unusedHook = (() => { throw new Error('unused by SkipOnboarding') }) as never
    const props = {
      stepId: 'welcome-notice', complete, openSection: vi.fn(),
      useSessions: unusedHook, useWorkspaces: unusedHook,
    }
    const { rerender } = render(<SkipOnboarding {...props} />)
    rerender(<SkipOnboarding {...props} />)
    expect(complete).toHaveBeenCalledTimes(1)
  })
})
