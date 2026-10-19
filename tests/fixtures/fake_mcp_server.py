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
                                    "title": "Synthetic concept",
                                    "url": "https://example.com/synthetic-concept",
                                    "publisher": "Wikipedia",
                                    "excerpt": "Synthetic source excerpt used only by the automated tests.",
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
