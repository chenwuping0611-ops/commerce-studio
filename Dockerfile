FROM node:24-bookworm-slim AS dependencies

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates openssl \
  && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build

COPY prisma ./prisma
RUN npx prisma generate

COPY nest-cli.json tsconfig.json tsconfig.build.json ./
COPY src ./src
COPY web ./web

RUN npm run build:all

FROM node:24-bookworm-slim AS production

ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates openssl \
  && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

# Keep the Prisma CLI in the runtime image so the entrypoint can apply
# committed migrations before the application process starts.
RUN npm install --no-save prisma@6.19.2

COPY --from=build /app/node_modules/.prisma ./node_modules/.prisma
COPY --from=build /app/node_modules/@prisma/client ./node_modules/@prisma/client
COPY --from=build /app/dist ./dist
COPY --from=build /app/web/dist ./web/dist
COPY prisma ./prisma
COPY deploy/docker/entrypoint.sh ./deploy/docker/entrypoint.sh

RUN chmod +x ./deploy/docker/entrypoint.sh \
  && mkdir -p /app/storage/media

EXPOSE 3000

ENTRYPOINT ["./deploy/docker/entrypoint.sh"]
