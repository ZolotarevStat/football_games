#!/bin/zsh
set -euo pipefail

cd /Users/aozolotarev/Documents/personal/outputs/worldcup_2026_predictions/telegram_bot_mvp

export PYTHONPATH=src
export PYTHONUNBUFFERED=1

# Current Codex/Happ/Tunnelblick setup needs this proxy to reach api.telegram.org.
export HTTP_PROXY=http://prx-squid-rev:9090
export HTTPS_PROXY=http://prx-squid-rev:9090
export http_proxy=http://prx-squid-rev:9090
export https_proxy=http://prx-squid-rev:9090
export NO_PROXY=127.0.0.1,localhost,.avito.ru

exec .venv/bin/python -m wc_predictions_bot.polling --trust-env-proxy
