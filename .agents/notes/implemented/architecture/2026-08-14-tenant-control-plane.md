# Agent Note: Tenant control plane reconstructs disposable Harness instances

Status: implemented

English | [中文](2026-08-14-tenant-control-plane.zh.md)

## Problem

Harness has no authenticated account, tenant ownership, or role model. Sharing one instance behind several proxy credentials does not isolate sessions, workspaces, settings, plugins, or failures.

Container-local plugin installation also makes lifecycle recovery ambiguous. A changed profile may prevent Harness from booting, while an artifact written only into a container disappears when that container is replaced.

## Decision

DeepHarness tenant management runs outside the Harness package graph. One tenant maps to one resource-limited, disposable Harness container and one host port. PostgreSQL owns tenant identity, reconstructable encrypted credentials, resource policy, operation history, and plugin desired, observed, and last-healthy versions.

Private Alibaba Cloud OSS owns immutable plugin package tarballs and compressed logical PostgreSQL backups. Each object key includes the tenant, plugin, and version. Upload commits require a tenant-owned key and a matching SHA-256 digest. Tenant containers receive short-lived object URLs and never receive Alibaba Cloud credentials.

Tenant `/data` is a tmpfs. Before Harness starts, the image queries the control plane with a hashed and encrypted tenant runtime token, downloads desired plugin releases, verifies each digest, and installs each exact tarball with package lifecycle scripts disabled. A failed release is omitted from boot and recorded for reconciliation. The base process remains available for recovery.

The tenant image exposes `deepharness-plugin-publish` and injects workspace guidance. Generated installable bundles are packed, uploaded through a short-lived URL, registered as immutable desired state, and only then allowed to request their own container rebuild. Upstream process-local `cordis_define` definitions are not silently presented as durable; they must be converted into an installable bundle first.

The control plane reconstructs a tenant by removing the labelled container, rotating its runtime token, decrypting its Basic Auth password, and creating a replacement from PostgreSQL state. Safe recovery sets `DSH_PLUGIN_SAFE_MODE=1` and does not restore tenant plugins. The runtime reports plugin observations only after Harness HTTP readiness, so a process that fails during boot cannot promote a release to last healthy.

PostgreSQL remains private to the Compose network and uses one durable database volume. A separate control-plane process exports logical table state to encrypted OSS objects daily. Tenant containers and plugin artifacts do not rely on Docker volumes.

## Alternatives considered

- **Add tenant ownership inside Harness core**: rejected because session, workspace, settings, credentials, APIs, WebSockets, and every plugin would need principal-aware authorization.
- **Keep SQLite and tenant Docker volumes**: rejected because a single host would remain the authority for instance and plugin recovery, preventing reliable reconstruction on another machine.
- **Mount OSS as the plugin filesystem**: rejected because object storage does not provide the filesystem semantics required by Node package resolution and plugin installation.
- **Give OSS credentials to each tenant**: rejected because a compromised plugin could access other tenant artifacts or backups; short-lived object URLs preserve tenant isolation.
- **Run package lifecycle scripts**: rejected because installation scripts execute outside the Cordis lifecycle and can modify the container before plugin validation.

## Consequences

- A tenant container can be deleted and rebuilt from PostgreSQL and OSS without retaining its writable layer.
- Plugin state distinguishes operator intent from runtime observation and does not mark a release healthy before the application is reachable.
- DSH session and workspace data remain ephemeral in tenant containers until their storage providers gain database and object-store implementations.
- PostgreSQL is an additional operational dependency and its data volume remains necessary; OSS logical backups provide host-loss recovery.
- The Docker socket remains host-equivalent authority and requires an authenticated administrative deployment.
