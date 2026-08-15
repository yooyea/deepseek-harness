#!/usr/bin/env node
/** Package the current plugin, persist it through the control plane, and optionally rebuild. */

import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

const baseUrl = process.env.DEEPHARNESS_CONTROL_PLANE_URL
const token = process.env.DEEPHARNESS_TENANT_TOKEN
if (!baseUrl || !token) {
  throw new Error('this command is available only inside a managed DeepHarness tenant')
}

const args = process.argv.slice(2)
const rebuild = args.includes('--rebuild')
const directory = resolve(args.find(argument => argument !== '--rebuild') ?? process.cwd())
const manifest = JSON.parse(await readFile(resolve(directory, 'package.json'), 'utf8'))
if (typeof manifest.name !== 'string' || typeof manifest.version !== 'string') {
  throw new Error('package.json must contain string name and version fields')
}
if (manifest.dsh?.bundle?.patch === undefined) {
  throw new Error('package.json must declare dsh.bundle.patch so Harness can activate the plugin')
}

const staging = await mkdtemp(resolve(tmpdir(), 'deepharness-plugin-'))
try {
  const packed = spawnSync('pnpm', ['pack', '--pack-destination', staging], {
    cwd: directory,
    encoding: 'utf8',
    timeout: 180_000,
  })
  if (packed.status !== 0) {
    throw new Error((packed.stderr || packed.stdout || `pnpm pack exited ${packed.status}`).trim())
  }
  const archiveName = packed.stdout.trim().split(/\r?\n/).at(-1)
  if (!archiveName) throw new Error('pnpm pack did not report an archive name')
  const archivePath = resolve(staging, basename(archiveName))
  const content = await readFile(archivePath)
  const sha256 = createHash('sha256').update(content).digest('hex')
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }

  const uploadReservation = await fetch(`${baseUrl}/plugins/uploads`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ name: manifest.name, version: manifest.version, sha256 }),
  })
  if (!uploadReservation.ok) {
    throw new Error(`upload reservation returned HTTP ${uploadReservation.status}: ${await uploadReservation.text()}`)
  }
  const upload = await uploadReservation.json()
  const uploaded = await fetch(upload.upload_url, {
    method: 'PUT',
    headers: upload.upload_headers ?? {},
    body: content,
  })
  if (!uploaded.ok) throw new Error(`OSS upload returned HTTP ${uploaded.status}: ${await uploaded.text()}`)

  const registered = await fetch(`${baseUrl}/plugins/register`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      name: manifest.name,
      version: manifest.version,
      sha256,
      artifact_key: upload.artifact_key,
      source_type: 'generated',
      source_ref: directory,
      manifest,
    }),
  })
  if (!registered.ok) {
    throw new Error(`plugin registration returned HTTP ${registered.status}: ${await registered.text()}`)
  }
  process.stdout.write(`Persisted ${manifest.name}@${manifest.version} (${sha256})\n`)

  if (rebuild) {
    const scheduled = await fetch(`${baseUrl}/rebuild`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!scheduled.ok) throw new Error(`tenant rebuild returned HTTP ${scheduled.status}`)
    process.stdout.write('Tenant rebuild scheduled; this connection will close while the container is replaced.\n')
  } else {
    process.stdout.write('Use the control-plane Rebuild action, or rerun with --rebuild, to activate it.\n')
  }
} finally {
  await rm(staging, { recursive: true, force: true })
}
