import urllib.request
import json
import os

url = "http://168.110.201.228/v1/workflows/run"
api_key = "app-51adf8a2a206dbc33fc7bd4d6c095f2e"

payload = {
    "inputs": {
        "prompt": "Test connection",
        "prompt_type": "GENERAL",
        "provider": "dify"
    },
    "response_mode": "blocking",
    "user": "debug-user"
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

print(f"Sending request to {url}...")
try:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(req) as res:
        print("Success!")
        print(res.read().decode())
except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}")
    print(e.read().decode())
except Exception as e:
    print(f"Error: {e}")
