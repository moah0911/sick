#!/usr/bin/env python3
"""Demo: Sick agent writes a fibonacci script and verifies it."""
import asyncio

from sick import SickAgent, detect


async def main():
    agent = SickAgent(llm=detect().create_llm())
    result = await agent.run(
        "Write a python script fibonacci.py that prints the first 20 fibonacci numbers. "
        "Then run it with `uv run python fibonacci.py` and verify the output is correct."
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
