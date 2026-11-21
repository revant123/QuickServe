# QuickServe customer app (Phase 13): build the static files with Node, serve
# them with nginx. Node is only in the first stage: the image that runs has no
# Node, no npm, no source code and no node_modules, just ~1 MB of built files.
#
#   docker build -t quickserve-app:dev frontend/
#   docker run --rm -p 8002:8080 quickserve-app:dev

# ---------- Stage 1: build ----------
FROM node:22.22-alpine3.24 AS build
WORKDIR /app
# The lock file first: `npm ci` (exact versions from package-lock.json) is
# cached as long as the dependencies don't change.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build && node scripts/check-size.mjs

# ---------- Stage 2: serve ----------
# nginx-unprivileged runs as user 101 and listens on 8080: it never needs root,
# so the pod can run with runAsNonRoot and a read-only root filesystem.
FROM nginxinc/nginx-unprivileged:1.31-alpine3.24
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
