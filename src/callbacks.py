# File: callbacks.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Implements events callbacks
# Date: 2021-04
# Copyright (c) 2021 vslg & contributors

import inspect
import random
import re
from contextlib import suppress
from dataclasses import dataclass, field
from functools import wraps
from itertools import zip_longest
from typing import TYPE_CHECKING, List

from mio.core.callbacks import CallbackGroup
from mio.rooms.contents.messages import Notice, Textual
from mio.rooms.events import TimelineEvent
from mio.rooms.room import Room
from mistune import markdown

from .commands import RootCommand
from .module import MarkovModule, MarkovRoom

if TYPE_CHECKING:
    from .client import MarkovClient


def admin(func):
    @wraps(func)
    async def wrapper(
        self,
        *args,
        markov_room: MarkovRoom,
        room:        Room,
        event:       TimelineEvent,
        **kwargs,
    ):
        user = room.state.members[event.sender]

        if user.user_id in markov_room.whitelist or user.power_level == 100:
            return await func(
                self,
                *args,
                markov_room = markov_room,
                room        = room,
                event       = event,
            )

        await room.timeline.send(
            Notice("You do not have permission to run this command"),
        )

    return wrapper


def command(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        params = list(inspect.signature(func).parameters.values())
        params = filter(lambda i: i.kind == i.POSITIONAL_OR_KEYWORD, params)
        params = list(params)[1:]
        args   = args[:len(params)]

        final_args = []

        for param, arg in zip_longest(params, args):
            if not param or param.annotation == param.empty:
                final_args.append(arg)
                continue

            if not arg:
                assert param.default != param.empty
                final_args.append(param.default)
                continue

            try:
                final_args.append(param.annotation(arg))
            except (ValueError, TypeError):
                # TODO: generate warning. generate error if empty param.defaut
                assert param.default != param.empty
                final_args.append(param.default)

        await func(self, *final_args, **kwargs)

    return wrapper


@dataclass
class Listener(CallbackGroup):
    client: "MarkovClient"

    rooms:     MarkovModule = field(init=False, repr=False)
    mentions:  List[str]    = field(default_factory=list)


    def __post_init__(self):
        self.rooms    = self.client.markov
        self.mentions = [
            self.client.user_id,
            # self.client.user_id.localpart,
            self.client.profile.name,
        ]


    async def on_timeline_text(
        self, room: Room, event: TimelineEvent[Textual],
    ):
        body        = event.content.body
        markov_room = self.rooms[room.id]

        print(f"message: {event.sender}: {body}")

        if self.client.user_id == event.sender:
            return

        for mention in self.mentions:
            regex = rf"^\s*(?i){re.escape(mention)}\W"
            if re.match(regex, body):
                body = "".join(re.split(regex, body)[1:])
                return await RootCommand(body, room, event, markov_room)()

        await markov_room.register_sentence(event.content.body)

        if random.random() < markov_room.freq:
            # TODO: average word count
            text = await markov_room.generate()
            await room.timeline.send(Notice(text))
