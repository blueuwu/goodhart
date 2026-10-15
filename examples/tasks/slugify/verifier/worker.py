"""Solution worker for check.py --isolated.

Usage: python -P worker.py WORKSPACE MODULE

Imports MODULE from WORKSPACE in this process (never in the grader's) and
answers one JSON request per line on stdin: {"fn", "args", "kwargs"} ->
{"ok": true, "value"} or {"ok": false, "type", "message"}. Values travel as
tagged JSON (see wire.py), never pickle, so the grader never deserialises code.
"""

import json
import os
import sys

from wire import decode, encode


def main() -> None:
    workspace, module_name = sys.argv[1], sys.argv[2]
    # Keep the protocol channel private: solution prints go to stderr.
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    sys.path.insert(0, workspace)
    module = __import__(module_name)
    for line in sys.stdin:
        req = json.loads(line)
        try:
            fn = getattr(module, req["fn"])
            value = fn(*decode(req["args"]), **decode(req["kwargs"]))
            resp = {"ok": True, "value": encode(value)}
        except Exception as e:  # noqa: BLE001 - every solution error goes back to the grader
            resp = {"ok": False, "type": type(e).__name__, "message": str(e)}
        proto.write(json.dumps(resp) + "\n")
        proto.flush()


if __name__ == "__main__":
    main()
