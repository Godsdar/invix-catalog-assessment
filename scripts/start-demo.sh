#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
fi
compose() {
  docker compose -f compose.yaml -f compose.tunnel.yaml "$@"
}
compose up -d --build --scale api=2 --scale frontend=2
attempt=0
while [ "$attempt" -lt 45 ]; do
  demo_url=$(compose logs --no-color tunnel 2>/dev/null | python3 -c '
import re,sys
urls=re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com",sys.stdin.read())
print(urls[-1] if urls else "")
')
  if [ -n "$demo_url" ]; then break; fi
  attempt=$((attempt + 1))
  sleep 2
done
if [ -z "$demo_url" ]; then
  echo "The HTTPS tunnel is not ready. Inspect: docker compose -f compose.yaml -f compose.tunnel.yaml logs tunnel"
  exit 1
fi
DEMO_URL="$demo_url" python3 - <<'PY'
from pathlib import Path
import os, secrets
p=Path('.env')
lines=p.read_text().splitlines()
values=dict(line.split('=',1) for line in lines if line and not line.startswith('#') and '=' in line)
values['MINI_APP_URL']=os.environ['DEMO_URL']
if not values.get('WEBHOOK_SECRET'):
    values['WEBHOOK_SECRET']=secrets.token_urlsafe(32)
for key in ['MINI_APP_URL','WEBHOOK_SECRET']:
    lines=[line for line in lines if not line.startswith(key+'=')]
    lines.append(key+'='+values[key])
p.write_text('\n'.join(lines)+'\n')
p.chmod(0o600)
PY
printf 'Catalog HTTPS: %s\n' "$demo_url"
if python3 - <<'PY'
from pathlib import Path
values=dict(line.split('=',1) for line in Path('.env').read_text().splitlines() if line and not line.startswith('#') and '=' in line)
raise SystemExit(0 if values.get('BOT_TOKEN') and values.get('ADMIN_IDS') else 1)
PY
then
  compose --profile telegram up -d --no-build --scale api=2 --scale frontend=2 --scale bot=2 --scale worker=2
  compose --profile telegram run --rm worker python -m catalog.register_webhook
else
  echo 'Catalog is live. Fill BOT_TOKEN and ADMIN_IDS in the ignored .env, then run this script again to connect Telegram.'
fi
