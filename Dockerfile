FROM node:24-bookworm AS builder

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

RUN corepack enable
WORKDIR /opt/dsh

COPY . .
RUN pnpm install --frozen-lockfile
RUN pnpm run build
RUN cp docker/http-random-uuid-polyfill.js apps/web/dist/http-random-uuid-polyfill.js \
    && node --input-type=module -e "import { readFileSync, writeFileSync } from 'node:fs'; const path = 'apps/web/dist/index.html'; const html = readFileSync(path, 'utf8'); const marker = '<head>'; if (!html.includes(marker)) throw new Error('web index is missing its head element'); writeFileSync(path, html.replace(marker, marker + '<script src=\"/http-random-uuid-polyfill.js\"></script>'))"

FROM node:24-bookworm-slim AS runtime

ENV PNPM_HOME=/pnpm
ENV PATH=$PNPM_HOME:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/* \
    && corepack enable

COPY --from=caddy:2.10.2 /usr/bin/caddy /usr/bin/caddy
COPY --from=builder /opt/dsh /opt/dsh

WORKDIR /opt/dsh
RUN chmod +x /opt/dsh/docker/entrypoint.sh /opt/dsh/docker/plugin-publish.mjs \
    && ln -s /opt/dsh/docker/plugin-publish.mjs /usr/local/bin/deepharness-plugin-publish \
    && mkdir -p /data

ENV DSH_HOME=/data
ENV DSH_ACCESS_USER=admin

VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/dsh/docker/entrypoint.sh"]
