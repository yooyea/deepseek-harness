/**
 * Restore desired tenant plugins from private, short-lived object URLs.
 * A failed plugin is recorded for the post-boot report and never blocks the
 * base Harness process from reaching its recovery UI.
 */

import { createHash } from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'

const baseUrl = process.env.DEEPHARNESS_CONTROL_PLANE_URL
const token = process.env.DEEPHARNESS_TENANT_TOKEN
const reportPath = '/tmp/deepharness-plugin-report.json'
const report = []

if (!baseUrl || !token || process.env.DSH_PLUGIN_SAFE_MODE === '1') {
  await writeFile(reportPath, JSON.stringify({ plugins: report }))
  process.exit(0)
}

try {
  const response = await fetch(`${baseUrl}/plugins`, {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(10_000),
  })
  if (!response.ok) throw new Error(`desired plugin request returned HTTP ${response.status}`)
  const desired = await response.json()
  await mkdir('/tmp/deepharness-plugins', { recursive: true })
  for (const plugin of desired.plugins ?? []) {
    const observed = { name: plugin.name, version: plugin.version, healthy: false, error: null }
    try {
      const artifactResponse = await fetch(plugin.download_url, { signal: AbortSignal.timeout(60_000) })
      if (!artifactResponse.ok) throw new Error(`artifact download returned HTTP ${artifactResponse.status}`)
      const content = Buffer.from(await artifactResponse.arrayBuffer())
      const digest = createHash('sha256').update(content).digest('hex')
      if (digest !== plugin.sha256) throw new Error('artifact checksum mismatch')
      const archive = `/tmp/deepharness-plugins/${digest}.tgz`
      await writeFile(archive, content)
      const result = spawnSync(
        'node',
        [
          '/opt/dsh/apps/cli/lib/bin.js',
          'plugin',
          '--profile',
          'web',
          'add',
          archive,
          '--ignore-scripts',
          '--save-exact',
        ],
        { encoding: 'utf8', timeout: 180_000 },
      )
      if (result.status !== 0) {
        throw new Error((result.stderr || result.stdout || `plugin installer exited ${result.status}`).trim())
      }
      observed.healthy = true
    } catch (error) {
      observed.error = error instanceof Error ? error.message : String(error)
      process.stderr.write(`DeepHarness plugin ${plugin.name}@${plugin.version} restore failed: ${observed.error}\n`)
    }
    report.push(observed)
  }
} catch (error) {
  process.stderr.write(`DeepHarness plugin restore unavailable: ${error instanceof Error ? error.message : String(error)}\n`)
}

await writeFile(reportPath, JSON.stringify({ plugins: report }))
