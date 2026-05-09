import os
import time
import hashlib
import hmac
import urllib.parse
import requests

def check_indodax_balance(api_key, api_secret):
    url = "https://indodax.com/tapi"
    nonce = int(time.time() * 1000)
    params = {
        "method": "getInfo",
        "nonce": nonce
    }
    query = urllib.parse.urlencode(params)
    signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha512).hexdigest()
    
    headers = {
        "Key": api_key,
        "Sign": signature
    }
    
    try:
        response = requests.post(url, data=params, headers=headers)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # Keys found in mac-engine/.env
    api_key = "ILLUBAFY-TTBAQISR-AQYDYX63-DOWFNF30-INXNTJD6"
    api_secret = "840c04b9db8ad3251039c4b44c2eed542013a5806e4cc81a362463f75fb8329397dd37d096280382"
    
    print("Checking Indodax balance...")
    result = check_indodax_balance(api_key, api_secret)
    print(result)
