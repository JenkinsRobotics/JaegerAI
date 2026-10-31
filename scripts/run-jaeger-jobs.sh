#!/bin/zsh
# 24/7 Jaeger job runner (launchd com.jenkinsrobotics.jaeger-jobs). Loopback only; no ports opened.
cd "$(dirname "$0")/.." || exit 1
exec nice -n 10 "$HOME/.jaeger/venv/bin/python" jaeger_ai/features/webui/api/jobs_runner.py
