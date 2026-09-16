ARG NODE_IMAGE=node@sha256:752ea8a2f758c34002a0461bd9f1cee4f9a3c36d48494586f60ffce1fc708e0e
ARG NGINX_IMAGE=nginx@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284
FROM ${NODE_IMAGE} AS builder

RUN corepack enable && corepack prepare pnpm@10.33.0 --activate
WORKDIR /build/frontend
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/tsconfig.json frontend/eslint.config.js ./
COPY frontend/apps/web-antd/package.json ./apps/web-antd/package.json
COPY frontend/packages/ui/package.json ./packages/ui/package.json
RUN pnpm install --frozen-lockfile
COPY frontend/apps/ ./apps/
COPY frontend/packages/ ./packages/
RUN pnpm build && test -f apps/web-antd/dist/index.html

FROM ${NGINX_IMAGE} AS runtime
COPY deploy/nginx/frontend.conf /etc/nginx/nginx.conf
COPY --from=builder /build/frontend/apps/web-antd/dist/ /usr/share/nginx/html/
RUN chown -R 10001:0 /usr/share/nginx/html /var/cache/nginx /var/log/nginx \
    && chmod -R g=u /usr/share/nginx/html /var/cache/nginx /var/log/nginx
USER 10001:0
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
