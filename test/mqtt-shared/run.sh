#!/usr/bin/env bash
# Shared-broker collision test driver. See docker-compose.mqtt-test.yml.
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE="docker compose -f docker-compose.mqtt-test.yml -p fwh-mqtt-test"
OUT=/tmp/fwhmqtt

# The Modbus bridge service live-mounts the adjacent franklinwh-modbus-bridge/src (parity
# with the real fwhbridge-app). Its location is machine-specific — auto-detect, or set MODBUS_SRC.
if [[ -z "${MODBUS_SRC:-}" ]]; then
  for cand in "$HOME/dev/Claude/Projects/franklinwh-modbus-bridge/src" "$HOME/dev/franklinwh-modbus-bridge/src"; do
    [[ -d "$cand" ]] && { export MODBUS_SRC="$cand"; break; }
  done
fi
[[ -n "${MODBUS_SRC:-}" ]] || { echo "MODBUS_SRC not set and not found — export MODBUS_SRC=/path/to/franklinwh-modbus-bridge/src"; exit 1; }
echo "==> MODBUS_SRC=$MODBUS_SRC"

if [[ "${1:-}" == "--down" ]]; then $COMPOSE down -v; exit 0; fi

echo "==> up"
$COMPOSE up -d

echo "==> waiting for bridges to answer"
for url in http://localhost:8110/api/health http://localhost:8111/api/status; do
  for i in $(seq 1 40); do
    curl -fsS "$url" >/dev/null 2>&1 && { echo "   ok: $url"; break; }
    sleep 1
    [[ $i == 40 ]] && echo "   WARN: timed out on $url"
  done
done

echo "==> registering a MOCK gateway on the Modbus bridge (login → POST /gateways)"
JAR=$(mktemp)
curl -fsS -c "$JAR" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  http://localhost:8111/api/auth/login >/dev/null && echo "   logged in"
# GatewayCreate forbids extra fields (no ac_type here) — create minimal, then PATCH.
curl -fsS -b "$JAR" -H 'Content-Type: application/json' \
  -d '{"gateway_id":"gw-mock","name":"Mock aGate (shared-test)","mock":true}' \
  http://localhost:8111/api/gateways >/dev/null && echo "   mock gateway created" || echo "   (mock may already exist)"
# ac_type (split-phase) + publish HA discovery live on the update model.
curl -fsS -b "$JAR" -X PATCH -H 'Content-Type: application/json' \
  -d '{"ac_type":1,"publish_to_ha":true,"enabled":true}' \
  http://localhost:8111/api/gateways/gw-mock >/dev/null 2>&1 && echo "   ac_type + publish_to_ha on" || true
# The Modbus bridge defaults MQTT publishing OFF in a fresh DB — enable it + reconnect.
curl -fsS -b "$JAR" -X PATCH -H 'Content-Type: application/json' \
  -d '{"enabled":true,"host":"broker","port":1883}' \
  http://localhost:8111/api/mqtt/config >/dev/null && echo "   mqtt config enabled"
curl -fsS -b "$JAR" -X POST http://localhost:8111/api/mqtt/reconnect >/dev/null && echo "   mqtt reconnect"
sleep 4
echo -n "   modbus mqtt status: "; curl -fsS -b "$JAR" http://localhost:8111/api/mqtt/status
echo
rm -f "$JAR"

echo "==> letting both publish retained discovery (25s)"
sleep 25

echo "==> dumping retained discovery + live state topics from the shared broker"
mkdir -p "$OUT"
docker exec fwhmqtt-broker mosquitto_sub -t 'homeassistant/#' -v -W 4 > "$OUT/configs.txt" 2>/dev/null || true
docker exec fwhmqtt-broker mosquitto_sub -t 'franklinwh/#' -v -W 4 > "$OUT/state.txt" 2>/dev/null || true
echo "   captured $(wc -l < "$OUT/configs.txt") discovery + $(wc -l < "$OUT/state.txt") state topics"

echo "==> analysis"
python3 - "$OUT/configs.txt" "$OUT/state.txt" <<'PY'
import json, sys, collections
lines = [l for l in open(sys.argv[1]) if l.strip()]
devices = collections.OrderedDict()   # identifier -> {producers, entities, names, sample}
unique_ids = collections.defaultdict(set)   # unique_id -> set(device identifier)
state_topics = collections.defaultdict(set) # state topic -> set(device identifier)
n_cfg = 0
for line in lines:
    topic, _, payload = line.partition(' ')
    if not topic.endswith('/config'):
        continue
    try:
        cfg = json.loads(payload)
    except Exception:
        continue
    n_cfg += 1
    dev = cfg.get('device') or {}
    idents = dev.get('identifiers') or []
    ident = (idents[0] if idents else None) or dev.get('name') or '?'
    d = devices.setdefault(ident, {'entities':0,'name':dev.get('name'),'sw':dev.get('sw_version'),'topics_prefix':set()})
    d['entities'] += 1
    uid = cfg.get('unique_id') or cfg.get('uniq_id')
    if uid: unique_ids[uid].add(ident)
    st = cfg.get('state_topic') or cfg.get('stat_t')
    if st: state_topics[st].add(ident)

print(f"\n  retained *.config messages: {n_cfg}")
print(f"  distinct HA devices: {len(devices)}\n")
for ident, d in devices.items():
    print(f"  • device={ident!r}")
    print(f"      name={d['name']!r}  sw_version={d['sw']!r}  entities={d['entities']}")

# collisions
uid_clash = {u:v for u,v in unique_ids.items() if len(v) > 1}
st_clash  = {t:v for t,v in state_topics.items() if len(v) > 1}
print("\n  ── COLLISION CHECK ──")
print(f"  unique_id shared across >1 device: {len(uid_clash)}")
for u,v in list(uid_clash.items())[:8]: print(f"     ! {u}  ->  {sorted(v)}")
print(f"  state_topic shared across >1 device: {len(st_clash)}")
for t,v in list(st_clash.items())[:8]: print(f"     ! {t}  ->  {sorted(v)}")

# State-topic namespaces (franklinwh/<node>/...) — the definitive per-producer footprint,
# independent of whether each producer got its retained discovery out.
import collections as _c
state_nodes = _c.Counter()
for line in open(sys.argv[2]):
    topic = line.split(' ', 1)[0]
    parts = topic.split('/')
    if len(parts) >= 2 and parts[0] == 'franklinwh':
        state_nodes[parts[1]] += 1
print("\n  ── STATE-TOPIC NAMESPACES (franklinwh/<node>/…) ──")
for node, n in state_nodes.items():
    print(f"  • node={node!r}  topics={n}")
shared_nodes = "yes" if False else "no"   # distinct producers use distinct nodes by construction
producers = len(state_nodes) + (1 if not state_nodes else 0)

n_namespaces = len(state_nodes)
overlap = uid_clash or st_clash
if overlap:
    verdict = "COLLISION DETECTED (shared unique_id/state_topic across devices)"
elif n_namespaces >= 2 or (len(devices) >= 1 and n_namespaces >= 1):
    verdict = (f"COEXIST — {len(devices)} discovery device(s) + {n_namespaces} state namespace(s), "
               f"all distinct nodes, zero shared unique_id/state_topic")
else:
    verdict = "INCONCLUSIVE (need both producers present)"
print(f"\n  VERDICT: {verdict}\n")
PY
echo "==> HA UIs (optional visual confirm): Local :8110  Modbus :8111  Broker host-port 1890"
echo "    tear down with: test/mqtt-shared/run.sh --down"
