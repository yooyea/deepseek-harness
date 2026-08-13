/** DeepHarness deployment branding and onboarding policy, browser half. */

import type { ClientContext } from '@deepseek-ai/dsh-client-runtime/client'
import type {} from '@deepseek-ai/dsh-client-ui-settings/client'
import { installDeepHarnessBranding } from './branding.ts'
import { SkipOnboarding } from './SkipOnboarding.tsx'

/** The slot registry is the only Cordis service used by this plugin. */
export const inject = ['slots']

/** Install browser branding and shadow the two upstream branded onboarding steps. */
export function apply(ctx: ClientContext): void {
  ctx.effect(() => installDeepHarnessBranding(document), 'ui-brand-deepharness: browser projection')

  ctx.slots.inject('settings.onboarding', () => {
    const disposeWelcome = ctx.slots.register({
      name: 'settings.onboarding',
      id: 'welcome-notice',
      order: -100,
      priority: -100,
    }, SkipOnboarding)
    const disposeOfficial = ctx.slots.register({
      name: 'settings.onboarding',
      id: 'deepseek-official',
      order: 0,
      priority: -100,
    }, SkipOnboarding)
    return () => {
      disposeOfficial()
      disposeWelcome()
    }
  })
}
