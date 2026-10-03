#!/bin/sh

set -eu

port="${PORT:-8000}"
interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
lan_ip=""

if [ -n "$interface" ]; then
  lan_ip="$(ipconfig getifaddr "$interface" 2>/dev/null || true)"
fi

if [ -z "$lan_ip" ]; then
  lan_ip="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
fi

if [ -n "$lan_ip" ]; then
  echo "局域网访问：http://${lan_ip}:${port}"
else
  echo "局域网访问：未检测到可用 IP，请检查网络连接"
fi

if [ "${1:-}" = "--open" ]; then
  (sleep 1; open "http://127.0.0.1:${port}" >/dev/null 2>&1) &
fi

exec python -m uvicorn app:app --reload --host 0.0.0.0 --port "$port"
