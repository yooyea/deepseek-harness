// @vitest-environment jsdom

import { Context } from '@deepseek-ai/cordis'
import { describe, expect, it } from 'vitest'
import { SlotRegistry } from '@deepseek-ai/dsh-client-runtime/client'
import { apply, inject } from '@deepseek-ai/dsh-client-ui-brand-deepharness/client'
import { SkipOnboarding } from '../src/client/SkipOnboarding.tsx'

const UpstreamStep = () => null

describe('DeepHarness plugin composition', () => {
  it('shadows both branded onboarding cells and restores upstream winners on teardown', async () => {
    document.title = 'DeepSeek Harness'
    const ctx = new Context()
    await ctx.plugin(SlotRegistry).await()
    const slots = ctx.get('slots') as SlotRegistry
    slots.register({
      name: 'root',
      children: { 'settings.onboarding': { kind: 'list', scope: 'root' } },
    } as never, () => null)
    slots.register({ name: 'settings.onboarding', id: 'welcome-notice', order: -100 }, UpstreamStep)
    slots.register({ name: 'settings.onboarding', id: 'deepseek-official', order: 0 }, UpstreamStep)

    expect(inject).toEqual(['slots'])
    const fiber = ctx.plugin({ inject: [...inject], apply })
    await fiber.await()

    const winners = slots.entriesOfSlot('settings.onboarding')
    expect(winners).toHaveLength(2)
    expect(winners.every(entry => entry.component === SkipOnboarding)).toBe(true)
    expect(winners.every(entry => entry.options.priority === -100)).toBe(true)
    expect(document.title).toBe('DeepHarness')

    await fiber.dispose()
    expect(slots.entriesOfSlot('settings.onboarding').every(entry => entry.component === UpstreamStep)).toBe(true)
    expect(document.title).toBe('DeepSeek Harness')
  })
})
