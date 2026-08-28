#!/usr/bin/env python3
"""Demo: Agent modifies itself by adding a ping tool and verifying it works."""
import asyncio

from sick import SickAgent, detect


async def main():
    agent = SickAgent(llm=detect().create_llm())
    result = await agent.modify_self(
        "Add a method `ping` to the agent that uses bash to ping a host "
        "and returns the result. Add it to agent.py with a proxy to a new Ping tool in tools/exec.py."
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
