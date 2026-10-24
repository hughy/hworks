#!/usr/bin/env bash
exec python3 - "$@" <<'PY'
import json, os, sys
with open(os.environ['FM_GH_CALLS'], 'a') as f:
    f.write(sys.argv[3] + '\n')
if os.environ.get('FM_GH_FAIL'):
    print('authentication failed', file=sys.stderr)
    sys.exit(1)
print(json.dumps(json.load(open(os.environ['FM_GH_DATA']))[sys.argv[3]]))
PY
