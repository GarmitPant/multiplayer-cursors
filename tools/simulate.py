"""Open N websocket clients into one room, each sending cursor updates at ~20Hz.
Usage: python tools/simulate.py [ws_url] [n]
"""
import asyncio
import json
import random
import sys
import time

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:8080/ws/demo"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
HZ = 20


async def client(i: int, stats: dict):
    async with websockets.connect(f"{URL}?name=bot{i}") as ws:
        async def recv():
            async for _ in ws:
                stats["recv"] += 1
        task = asyncio.create_task(recv())
        try:
            while True:
                await ws.send(json.dumps({
                    "type": "cursor", "x": random.random(), "y": random.random()
                }))
                stats["sent"] += 1
                await asyncio.sleep(1 / HZ)
        finally:
            task.cancel()


async def main():
    stats = {"sent": 0, "recv": 0}
    [asyncio.create_task(client(i, stats)) for i in range(N)]
    t0 = time.time()
    while True:
        await asyncio.sleep(2)
        dt = time.time() - t0
        print(f"[{dt:5.1f}s] clients={N} "
              f"sent/s={stats['sent']/dt:8.0f} recv/s={stats['recv']/dt:9.0f}")


if __name__ == "__main__":
    asyncio.run(main())
