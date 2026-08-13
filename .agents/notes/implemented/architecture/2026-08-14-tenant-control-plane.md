# Agent Note: Tenant control plane provisions isolated Harness instances

Status: implemented

English | [中文](2026-08-14-tenant-control-plane.zh.md)

## Problem

Harness has no authenticated account, tenant ownership, or role model. The deployment's `admin` credential protects one shared instance at the reverse proxy, so adding more proxy credentials would still expose the same sessions, workspaces, settings, and data to every operator.

Adding tenant ownership inside Harness would couple deployment administration to its fast-moving session, workspace, settings, credential, and client APIs. The immediate deployment needs isolated users, bounded server capacity, and an operator view without changing those product domains.

## Decision

DeepHarness tenant management runs as a deployment-owned control plane outside the Harness package graph. One tenant maps to one resource-limited Harness container, one host port, and one persistent Docker volume. The control plane stores desired instance state and administrative operations in SQLite with WAL mode enabled.

The integration surface is the published Harness image, its `/data` volume, its Basic Auth environment variables, and Docker container state. Harness session, workspace, credential, and plugin persistence remains unchanged.

Creating a tenant checks sampled host CPU, one-minute load, available memory, disk free percentage, and the sum of active tenant CPU and memory reservations. Error-state instances continue to count as reserved because Docker resources may still exist until an administrator removes them.

The control plane requires a separate administrator credential and a mutation header for state-changing API requests. Tenant passwords are generated once and are not stored in SQLite. Docker operations validate a management label before changing an existing container, and creation accepts only configured resource limits, image, port range, and generated names.

Removing a tenant deletes its container but preserves its volume unless the API caller explicitly requests purge. Operation logs retain the outcome and error detail. SQLite and tenant Docker volumes are independent backup units.

## Alternatives considered

- **Add users and tenant ownership to Harness core**: rejected because every session, workspace, settings, credential, API, and WebSocket path would need principal-aware authorization and migration.
- **Add several Caddy Basic Auth users to one Harness instance**: rejected because it separates credentials but not data, settings, privileges, or audit ownership.
- **Store tenants only as generated Compose files**: rejected because lifecycle state, resource admission, runtime reconciliation, and operation history need queryable durable state.
- **Use PostgreSQL for the control plane**: rejected for the single-controller deployment because SQLite WAL provides the required durability and transactions without another service.

## Consequences

- Tenants receive separate runtime state, data volumes, credentials, resource limits, and failure domains while consuming the same immutable Harness image.
- Harness upgrades remain image changes and do not require tenant-aware migrations inside Harness.
- The control plane is a single active process while it uses SQLite; horizontal control-plane replicas are unsupported.
- Mounting the Docker socket grants host-equivalent container control, so the service remains an administrative component behind authentication and should move to a narrow host-agent API before multi-host deployment.
- Standard-library unit tests cover admission, SQLite updates, and lifecycle orchestration; API smoke tests cover authentication, health, dashboard serialization, and static delivery.
