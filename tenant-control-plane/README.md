# DeepHarness Tenant Control Plane

English | [中文](README.zh.md)

The tenant control plane provisions disposable, resource-limited Harness containers. PostgreSQL is the authority for tenant, credential, plugin, health, and operation state; private Alibaba Cloud OSS stores immutable plugin releases and logical database backups.

## Capabilities

- HTTP Basic protected administrator dashboard
- PostgreSQL tenant and plugin desired-state records
- private, per-object AES-256 encrypted, versioned OSS plugin artifacts
- tenant create, start, stop, restart, rebuild, recovery, and removal
- one-time generated tenant password encrypted at rest for reconstruction
- host and per-container resource monitoring and admission
- desired, observed, and last-healthy plugin versions
- tenant-scoped runtime tokens and short-lived artifact URLs
- daily compressed logical database backups to OSS

Tenant containers use an in-memory `/data` filesystem and contain no Alibaba Cloud credential. The image restores desired plugins through the control plane before Harness boots, verifies every SHA-256 digest, installs with package lifecycle scripts disabled, and reports observations only after the Harness HTTP process becomes ready.

`rebuild` deletes and recreates a container from PostgreSQL and OSS. `recover` performs the same replacement with `DSH_PLUGIN_SAFE_MODE=1`, which starts the base image without tenant plugins.

## Run with Docker Compose

Copy `.env.example` to `.env`, replace every placeholder, then run:

```bash
docker compose up -d
```

The Compose application starts PostgreSQL, the original Harness instance, the tenant control plane, and its backup worker. PostgreSQL is private to the Compose network and uses the `deepharness-postgres-data` volume. Provisioned tenant containers have no durable Docker volume.

Default endpoints:

- Harness: `http://SERVER:8080`
- Tenant control plane: `http://SERVER:8090`
- Provisioned tenants: `http://SERVER:8100` through `http://SERVER:8199`

GitHub Actions creates a private OSS bucket when `OSS_BUCKET` is not configured, enables versioning, incomplete-upload cleanup, and 90-day noncurrent-version expiration, then writes the resolved OSS configuration to the server deployment. Every plugin and backup upload explicitly requests AES-256 server-side encryption.

`OSS_ENDPOINT` must use Alibaba Cloud's S3-compatible form, for example `https://s3.oss-cn-shanghai.aliyuncs.com`. The boto3 client uses the OSS-compatible V2 signature mode.

## Plugin artifact protocol

A tenant runtime requests an upload URL, uploads one npm package tarball, and commits its metadata. The control plane accepts the commit only when the key belongs to that tenant and the downloaded artifact matches the declared SHA-256 digest. PostgreSQL then records the version as desired.

On container replacement, the image requests desired releases with its tenant bearer token, downloads each short-lived URL, verifies the digest again, and runs the profile plugin installer with `--ignore-scripts` and an exact file reference. One failed plugin is reported and skipped; it cannot prevent the base Harness process from starting.

Managed tenants also provide `deepharness-plugin-publish`. A model or developer can turn generated code into an installable DSH bundle, assign a new package version, then run `deepharness-plugin-publish /path/to/plugin --rebuild`. The command packs it, uploads it without exposing cloud credentials, commits its desired state, and schedules replacement only after persistence succeeds. The injected workspace `AGENTS.md` teaches this workflow and warns against restarting the disposable container directly.

Process-local `cordis_define` packages remain temporary by upstream design. To survive replacement and appear in the control-plane inventory, convert the result into a prebuilt installable bundle and publish it with the command above.

## Security

The Docker socket grants the control plane host-level container authority, so the service must remain an authenticated administrative component. Docker operations accept only the configured image, port range, generated names, and management-labelled containers.

Alibaba Cloud access keys are available only to the control-plane and backup containers. Use a dedicated RAM identity restricted to the single OSS bucket. Tenant passwords and runtime tokens are encrypted with `CONTROL_PLANE_SECRET_KEY`; only runtime-token hashes participate in authentication lookups.

PostgreSQL's volume protects database restarts, while OSS backups protect recovery from loss of the Docker host. Restore automation is intentionally separate from ordinary deployment so a broken or partial backup cannot overwrite a live database.

## Validation

```bash
cd tenant-control-plane
python -m pip install -r requirements.txt
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q app tests scripts
node --check ../docker/plugin-bootstrap.mjs
node --check ../docker/plugin-report.mjs
```
