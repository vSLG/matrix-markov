# File: module.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Implements Client modules
# Date: 2021-04
# Copyright (c) 2021 vslg & contributors

import random
import re
from dataclasses import dataclass, field
from typing import Counter, Dict, Optional, Set, Tuple

from aiopath import AsyncPath
from mio.core.data import IndexableMap, Runtime
from mio.core.files import decode_name, encode_name
from mio.core.ids import RoomId, UserId
from mio.module import JSONClientModule


@dataclass
class MarkovRoom(JSONClientModule):
    id: RoomId

    whitelist: Set[UserId]                    = field(default_factory=set)
    freq:      float                          = field(default=0.0)
    pairs: Counter[Tuple[Optional[str], str]] = field(default_factory=Counter)


    @property
    def path(self) -> AsyncPath:
        room_id = encode_name(self.id)
        return self.client.path.parent / "markov" / (room_id + ".json")


    async def register_sentence(self, sentence: str) -> None:
        words = re.split(r"(?![',.\!\?:\-\/\\;\=\@])[\W_]+", sentence)

        if not words:
            return

        words = [i for i in words if i != ""]

        await self._register_pair((None, words[0]))

        for pair in zip(words[:-1], words[1:]):
            await self._register_pair(pair)

        await self.save()


    async def generate(
        self,
        word_count:    int           = 10,
        starting_word: Optional[str] = None,
    ) -> str:
        assert(word_count > 1)

        final_sentence = [starting_word] if starting_word else []

        has_starting_word = False

        for k in self.pairs.keys():
            if k[0] == starting_word:
                has_starting_word = True
                break

        if not has_starting_word:
            starting_word = None

        for _ in range(word_count):
            words_and_weights = {
                k[1]: v for k, v in self.pairs.items() if k[0] == starting_word
            }

            words   = list(words_and_weights.keys())
            weights = list(words_and_weights.values())

            if not words:
                starting_word = None
                final_sentence[-1] += "."
                continue

            starting_word   = random.choices(words, weights)[0]
            final_sentence += [starting_word]

        return " ".join(final_sentence)


    async def _register_pair(self, pair: Tuple[Optional[str], str]) -> None:
        print(f"Registered pair: {pair}")
        self.pairs[pair] += 1


@dataclass
class MarkovModule(JSONClientModule, IndexableMap[RoomId, MarkovRoom]):
    _data: Runtime[Dict[RoomId, MarkovRoom]] = field(default_factory=dict)

    @property
    def path(self):
        return self.client.path.parent / "markov_settings.json"


    async def load(self) -> "MarkovModule":
        async for room_dir in (self.client.path.parent / "rooms").glob("!*"):
            id             = RoomId(decode_name(room_dir.name))
            self._data[id] = await MarkovRoom(self.client, id=id).load()

        return self
