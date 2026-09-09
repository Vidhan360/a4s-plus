# A4S+ frontend image (Next.js 15 standalone output).
#
# Build context: repository root.
#   docker build -f infra/docker/frontend.Dockerfile \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 \
#     -t a4s-plus/frontend .
#
# NOTE: written but NOT built in this environment (no Docker daemon available).

FROM node:24-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# ---------------------------------------------------------------- build
FROM node:24-slim AS build
WORKDIR /app

# NEXT_PUBLIC_* values are inlined at build time by Next.js, so the browser
# origin of the API must be known here and not only at runtime.
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM node:24-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN useradd --create-home --uid 10002 a4s

COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

USER a4s
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]