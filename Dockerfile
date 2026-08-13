FROM node:24-bookworm AS builder

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

RUN corepack enable
WORKDIR /opt/dsh

COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm run build

FROM node:24-bookworm-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=caddy:2.10.2 /usr/bin/caddy /usr/bin/caddy
COPY --from=builder /opt/dsh /opt/dsh

WORKDIR /opt/dsh
RUN chmod +x /opt/dsh/docker/entrypoint.sh \
    && mkdir -p /data

ENV DSH_HOME=/data
ENV DSH_ACCESS_USER=admin

VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/dsh/docker/entrypoint.sh"]
