import json
import sys


for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "fake"}}
    elif method == "tools/call":
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "results": [
                                {
                                    "title": "Quadratic formula",
                                    "url": "https://en.wikipedia.org/wiki/Quadratic_formula",
                                    "publisher": "Wikipedia",
                                    "excerpt": "The quadratic formula gives solutions of a quadratic equation.",
                                }
                            ]
                        }
                    ),
                }
            ]
        }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
