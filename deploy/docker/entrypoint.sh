#!/bin/sh
set -eu

echo "[commerce-studio] applying database migrations"
npx prisma migrate deploy

echo "[commerce-studio] starting application"
exec node dist/src/main.js
