import os
from dotenv import load_dotenv
from Core.Exchange.indodax import IndodaxGateway
import asyncio

async def test():
    load_dotenv()
    print(f"Key: {os.environ.get('INDODAX_API_KEY')}")
    gw = IndodaxGateway()
    res = await gw.get_info()
    print(res)

asyncio.run(test())
