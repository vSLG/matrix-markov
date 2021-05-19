# File: module.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Implements Client modules
# Date: 2021-04
# Copyright (c) 2021 vslg & contributors

import asyncio
from pathlib import Path

from mio.client import Client
from mio.core.data import JSONLoadError
from mio.net.errors import ServerError

from .callbacks import Listener
from .client import MarkovClient


async def login_client(client: Client) -> None:
    print("Creating credentials file")

    while client.access_token == "":
        user_id    = input("Enter your user or user_id: ")
        password   = input("Enter your password: ")
        homeserver = input("Enter homeserver: ")

        client.server = homeserver

        await client.auth.login_password(user=user_id, password=password)

    await client.save()
    print()


async def main():
    print("Matrix markov bot\n")

    # Try loading account from disk
    client = MarkovClient(Path("./account"))

    try:
        await client.load()
    except JSONLoadError:
        await login_client(client)

    client.rooms.callback_groups.append(Listener(client))

    await client.sync.loop()


if __name__ == "__main__":
    asyncio.run(main())
