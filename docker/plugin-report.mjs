/** Report prepared plugins only after the Harness HTTP process becomes ready. */

import { readFile } from 'node:fs/promises'

const baseUrl = process.env.DEEPHARNESS_CONTROL_PLANE_URL
const token = process.env.DEEPHARNESS_TENANT_TOKEN

if (!baseUrl || !token || process.env.DSH_PLUGIN_SAFE_MODE === '1') process.exit(0)

for (let attempt = 0; attempt < 30; attempt += 1) {
  try {
    const response = await fetch('http://127.0.0.1:3080/', { signal: AbortSignal.timeout(2_000) })
    if (response.ok) {
      const payload = await readFile('/tmp/deepharness-plugin-report.json', 'utf8')
      const reportResponse = await fetch(`${baseUrl}/plugins/report`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: payload,
        signal: AbortSignal.timeout(10_000),
      })
      if (!reportResponse.ok) throw new Error(`plugin report returned HTTP ${reportResponse.status}`)
      process.exit(0)
    }
  } catch {
    // Readiness and reporting retry together; the main process owns final failure.
  }
  await new Promise(resolve => setTimeout(resolve, 2_000))
}
