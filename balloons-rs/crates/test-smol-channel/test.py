#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/dan/Development/balloons/balloons-rs/target/release')

import asyncio

async def main():
    import test_smol_channel

    print("Connecting (this mimics fantoccini's connect flow)...")
    client = await test_smol_channel.Client.connect()
    print("Connected!")

    print("Sleeping 1s...")
    await asyncio.sleep(1)

    print("Sending message 1 and waiting for response...")
    try:
        response = await asyncio.wait_for(client.send("Hello from Python!"), timeout=5)
        print(f"Got response: {response}")
    except asyncio.TimeoutError:
        print("TIMEOUT waiting for response!")

    print("Sleeping 1s...")
    await asyncio.sleep(1)

    print("Sending message 2 and waiting for response...")
    try:
        response = await asyncio.wait_for(client.send("Second message!"), timeout=5)
        print(f"Got response: {response}")
    except asyncio.TimeoutError:
        print("TIMEOUT waiting for response!")

    print("Test complete!")

if __name__ == "__main__":
    asyncio.run(main())
