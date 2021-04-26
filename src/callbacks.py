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
from mio.rooms.contents.messages import Notice, TextBase
from mio.rooms.events import TimelineEvent
from mio.rooms.room import Room
from mistune import markdown

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
        self, room: Room, event: TimelineEvent[TextBase],
    ):
        body        = event.content.body
        markov_room = self.rooms[room.id]

        print(f"message: {event.sender}: {body}")

        if self.client.user_id == event.sender:
            return

        if (any(
                re.match(rf"^\s*{re.escape(m)}\W", body)
                for m in self.mentions
        )):
            return await self._handle_command(room, event)

        await markov_room.register_sentence(event.content.body)

        if random.random() < markov_room.freq:
            # TODO: average word count
            text = await markov_room.generate()
            await room.timeline.send(Notice(text))


    async def _handle_command(
        self, room: Room, event: TimelineEvent[TextBase],
    ) -> None:
        body        = event.content.body
        markov_room = self.rooms[room.id]

        for mention in self.mentions:
            regex = rf"^\s*{re.escape(mention)}\W"
            if re.match(regex, body):
                command_body = "".join(re.split(regex, body)[1:])
                break

        command_parts = re.split(r"[\s]+", command_body)
        command = command_parts[0].lower()

        func = getattr(self, command, None)

        if func:
            return await func(
                *command_parts[1:],
                markov_room = markov_room,
                room        = room,
                event       = event,
            )

        return await room.timeline.send(Notice("Unknown command"))



    @command
    async def generate(
        self,
        count:         int = 10,
        starting_word: str = None,
        *args,
        markov_room: MarkovRoom,
        room:        Room,
        **kwargs,
    ):
        count = max(min(count, 100), 2)
        text = Notice(await markov_room.generate(count, starting_word))
        await room.timeline.send(text)


    @command
    async def top(
        self,
        top: int = 10,
        *args,
        markov_room: MarkovRoom,
        room:        Room,
        **kwargs,
    ):
        top = max(min(top, 30), 0)

        reply  = f"Top {top} pairs:\n\n"
        reply += "Word 1 | Word 2 | Count\n"
        reply += "--- | --- | ---\n"
        reply += "\n".join(
            "%-20s | %-20s | %-5s" % (i[0][0], i[0][1], i[1])
            for i in markov_room.pairs.most_common(top)
        )

        message                = Notice(reply)
        message.format         = "org.matrix.custom.html"
        message.formatted_body = markdown(reply)

        return await room.timeline.send(message)


    @command
    async def stats(self, *args, markov_room, room, **kwargs):
        return await room.timeline.send(
            Notice(f"Total learned pairs: {len(markov_room.pairs)}"),
        )


    @command
    @admin
    async def freq(
        self,
        frequency: float,
        *args,
        markov_room: MarkovRoom,
        room:        Room,
        **kwargs,
    ):
        markov_room.freq = frequency
        await markov_room.save()
        await room.timeline.send(Notice(f"Frequency is now {frequency}"))


    @admin
    @command
    async def remove(
        self,
        first:  str,
        second: str,
        *args,
        markov_room: MarkovRoom,
        room:        Room,
        **kwargs,
    ):
        pair = None

        with suppress(KeyError):
            pair = markov_room.pairs.pop((first, second))

        if pair:
            return await room.timeline.send(Notice("Erased pair"))

        await room.timeline.send(Notice("Pair not found"))


    @command
    @admin
    async def whitelist(
        self,
        action: str = "",
        target: str = "",
        *args,
        markov_room: MarkovRoom,
        room:        Room,
        **kwargs,
    ):
        action = action.lower()
        user   = room.state.members.get(target.lower(), None)

        if action != "" and not user:
            return await room.timeline.send(
                Notice("Please specify a valid user ID and make sure they "
                       "are in the room"),
            )

        if action == "add":
            markov_room.whitelist.add(user.user_id)
            await markov_room.save()
            return await room.timeline.send(
                Notice(f"Added {user.user_id} to whitelist"),
            )
        elif action == "remove":
            markov_room.whitelist.discard(user.user_id)
            await markov_room.save()
            return await room.timeline.send(
                Notice(f"Removed {user.user_id} from whitelist"),
            )

        await room.timeline.send(
            Notice("Current users in the whitelist:\n\n" +
                   "\n".join(markov_room.whitelist)),
        )
