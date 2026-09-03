#!/usr/bin/env bash
set -euo pipefail

export FLASK_CONFIG=production
export PEAR_AI_LOG_DIR="${PEAR_AI_LOG_DIR:-/var/log/pear-ai}"
export PEAR_AI_APP_LOG_FILE="${PEAR_AI_APP_LOG_FILE:-/var/log/pear-ai/pear-ai.log}"

exec gunicorn -c gunicorn.conf.py "applications:create_app('production')"
