# File: callbacks.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Implements events callbacks
# Date: 2021-04
# Copyright (c) 2021 vslg & contributors

import random
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

from mio.core.callbacks import CallbackGroup
from mio.rooms.contents.messages import Notice, Textual
from mio.rooms.contents.users import Member
from mio.rooms.events import StateEvent, TimelineEvent
from mio.rooms.room import Room

from .commands.general import RootCommand
from .module import MarkovModule, MarkovRoom

if TYPE_CHECKING:
    from .client import MarkovClient


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
        body        = event.content.stripped_body
        markov_room = self.rooms[room.id]

        print(f"message: {event.sender}: {body}")

        if self.client.user_id == event.sender:
            return

        for mention in self.mentions:
            regex = rf"^\s*(?i){re.escape(mention)}\W"
            if re.match(regex, body):
                body = "".join(re.split(regex, body)[1:])
                return await RootCommand(body, room, event, markov_room)()

        await markov_room.register_sentence(body)

        if random.random() < markov_room.freq:
            # TODO: average word count
            text = await markov_room.generate(word_count=20)
            await room.timeline.send(Notice(text))


    async def on_join_state(
        self, room: Room, event: StateEvent[Member],
    ):
        if not event.content.absent and event.sender == self.client.user_id:
            self.rooms._data[room.id] = await MarkovRoom(
                self.client, id=room.id,
            ).load()
