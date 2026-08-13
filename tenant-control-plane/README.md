# DeepHarness Tenant Control Plane

English | [中文](README.zh.md)

The tenant control plane provisions one resource-limited Harness container and one persistent Docker volume per tenant. It is independent from the Harness package graph and communicates with Harness only through its published image and environment variables.

## Capabilities

- HTTP Basic protected administrator dashboard
- SQLite persistence in WAL mode
- tenant create, start, stop, restart, and removal operations
- one-time generated tenant password
- isolated data volume and host port per tenant
- host CPU, load, memory, and disk dashboard
- per-container CPU and memory usage
- admission checks against actual pressure and reserved resource limits
- immutable lifecycle operation log

Removal preserves the tenant data volume by default. The API supports explicit volume purging, but the dashboard intentionally does not expose that destructive option.

## Run with Docker Compose

The repository-level `docker-compose.yml` starts both the original Harness instance and the control plane. Copy `.env.example` to `.env`, replace both administrator passwords, then run:

```bash
docker compose up -d
```

The default endpoints are:

- Harness: `http://SERVER:8080`
- Tenant control plane: `http://SERVER:8090`
- Provisioned tenants: `http://SERVER:8100` through `http://SERVER:8199`

Production firewalls must explicitly allow only the required ports. Put the control plane behind a private network or a TLS reverse proxy before giving access to additional administrators.

The automated first deployment reuses the existing Harness administrator password for the control plane so the operator can log in immediately. The two values can be separated later in the server-side `.env` file.

## Security model

Mounting `/var/run/docker.sock` grants the control-plane process host-level container management power. The service therefore accepts only a fixed Harness image, allocates ports from a configured range, generates container and volume names from validated slugs, and refuses lifecycle actions against containers without its management label.

The control plane does not persist tenant plaintext passwords. A generated password is returned once after successful creation; Docker retains it in the managed container configuration so that the Harness entry point can enforce Basic Auth.

## Validation

Pure domain and SQLite tests use the Python standard library:

```bash
cd tenant-control-plane
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q app tests
```
