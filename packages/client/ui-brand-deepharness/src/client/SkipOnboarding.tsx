import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import type { PropsRuntime } from '@deepseek-ai/dsh-client-ui-slots'
import type {} from '@deepseek-ai/dsh-client-ui-settings/client'

/** Props supplied by the settings onboarding coordinator. */
export type SkipOnboardingProps = PropsRuntime<'settings.onboarding'>

/** Complete a shadowed upstream onboarding entry without painting UI. */
export function SkipOnboarding({ complete }: SkipOnboardingProps): ReactNode {
  const completed = useRef(false)
  useEffect(() => {
    if (completed.current) return
    completed.current = true
    complete()
  }, [complete])
  return null
}
