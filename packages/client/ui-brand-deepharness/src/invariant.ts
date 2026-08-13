/** Package-owned invariant companion for the DeepHarness branding overlay. */

import type { Context } from '@deepseek-ai/cordis'
import type { InvariantInstaller } from '@deepseek-ai/dsh-invariants'

const PACKAGE_NAME = '@deepseek-ai/dsh-client-ui-brand-deepharness'

/** Cordis companion plugin name. */
export const name = 'client-ui-brand-deepharness-invariant'
/** Service required before package ownership can be registered. */
export const inject = ['invariants']

/**
 * No runtime invariant: the client effect owns every DOM mutation and slot
 * shadow, and its tests prove that teardown restores both surfaces.
 */
const install: InvariantInstaller = () => {}

/** Register the package invariant companion. */
export const apply = (ctx: Context): Promise<() => void> =>
  Promise.resolve(ctx.invariants.register(PACKAGE_NAME, install))
