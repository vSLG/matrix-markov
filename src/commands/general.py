# File: general.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Markov chain related commands and general commands
# Date: 2021-07
# Copyright (c) 2021 vslg & contributors

from contextlib import suppress
from typing import List

from mio.rooms.contents.messages import Notice
from mistune import markdown

from .base import MarkovCommand


class RootCommand(MarkovCommand):
    """kk eae, markov here

    bottom text

    Usage:
        mark help | -h | --help
        mark <command> [<args>...]

    Options:
        -h, --help     Shows this help.
    """


    async def __call__(self):
        args = self.args or {}

        if (not args or args["--help"] or args["help"]):
            return await self.help(usage_only=False)

        await super().__call__()


@RootCommand.add
class GenerateCommand(MarkovCommand):
    """Generates a sentence

    Usage:
        generate [-c COUNT] [<starting_word>]
        generate -h | --help

    Options:
        -h, --help               Shows this help.
        -c COUNT, --count COUNT  How many words to generate.
                                 [default: 20]
    """

    name:    str       = "generate"
    aliases: List[str] = ["g", "gen"]


    async def __call__(self):
        count         = int(self.args.pop("--count"))
        count         = max(min(count, 100), 2)
        starting_word = self.args.pop("<starting_word>") or None
        text          = await self.markov_room.generate(count, starting_word)

        await self.room.timeline.send(Notice(text))


@RootCommand.add
class FrequencyCommand(MarkovCommand):
    """How frequent the bot should send messages

    Usage:
        frequency [<value>]
        frequency -h | --help

    Options:
        -h, --help  Shows this help.

    Arguments:
        <value>  Sets bot freqency to <value>.
    """

    name:    str       = "frequency"
    aliases: List[str] = ["freq", "f"]
    admin:   bool      = True


    async def __call__(self):
        try:
            number                = float(self.args.pop("<value>").rstrip("%"))
            number                = max(min(number, 100.0), 0.0)
            self.markov_room.freq = number / 100

            await self.markov_room.save()
            await self.room.timeline.send(
                Notice("Frequency is now %.0f%%" % number))
        except (ValueError, KeyError):
            await self.room.timeline.send(
                Notice("Frequency is %.0f%%" % (self.markov_room.freq * 100)),
            )


@RootCommand.add
class StatsCommand(MarkovCommand):
    """How many pairs learned + most typed pairs

    Usage:
        stats [<count>]
        stats -h | --help

    Options:
        -h, --help  Shows this help.

    Arguments:
        <count>  Displays top <count> pairs typed.
                 [minimum: 1, maximum: 30]
    """

    name: str = "stats"
    aliases: List[str] = ["st", "s"]


    async def __call__(self):
        count = int(self.args.pop("<count>") or 10)
        count = max(min(count, 30), 1)

        reply  = f"Total learned pairs: **{len(self.markov_room.pairs)}**\n\n"
        reply += f"Top **{count}** pairs:\n\n"
        reply += "Word 1 | Word 2 | Count\n"
        reply += "--- | --- | ---\n"
        reply += "\n".join(
            "%-20s | %-20s | %-5s" % (i[0][0], i[0][1], i[1])
            for i in self.markov_room.pairs.most_common(count)
        )

        message                = Notice(reply)
        message.format         = "org.matrix.custom.html"
        message.formatted_body = markdown(reply)

        return await self.room.timeline.send(message)


@RootCommand.add
class DeleteCommand(MarkovCommand):
    """Deletes word(s) or pair(s) from learned data

    Usage:
        delete -p (<word> <word>)...
        delete <word> [<word>...]
        delete -h | --help

    Options:
        -h, --help  Shows this help.
        -p, --pair  Pair(s) of words to delete.

    Arguments:
        <word>  Word(s) to delete from data. Keep in
                mind the bot will delete every pair
                containing this/these word(s).
    """

    name:    str       = "delete"
    aliases: List[str] = ["del", "rm", "d"]
    admin:   bool      = True


    async def __call__(self):
        pairs = self.args.pop("<word>")

        if self.args.pop("--pair"):
            return await self.remove_pairs(pairs)

        await self.remove_words(pairs)


    async def remove_pairs(self, pairs) -> None:
        deleted = 0
        to_remove = zip(pairs[::1], pairs[1::2])

        for pair in to_remove:
            with suppress(KeyError):
                del self.markov_room.pairs[pair]
                deleted += 1

        return await self.room.timeline.send(
            Notice(f"Removed {deleted} pairs"),
        )


    async def remove_words(self, words) -> None:
        to_remove = []

        for pair in self.markov_room.pairs.keys():
            if (pair[0] in words or pair[1] in words):
                to_remove.append(pair)

        for pair in to_remove:
            del self.markov_room.pairs[pair]

        await self.markov_room.save()

        body  = f"Removed {len(to_remove)} pairs containing "
        body += "'"
        body += "', '".join(words)
        body += "'"
        return await self.room.timeline.send(Notice(body))


@RootCommand.add
class WhitelistCommand(MarkovCommand):
    """Manages this room's whitelist

    Whitelisted users are able to run admin-only commands,
    whether they have enough power level or not. Be careful,
    whitelisting an user makes they able to also manipulate
    whitelist.

    Usage:
        whitelist (add | del) <user>
        whitelist -h | --help
        whitelist

    Options:
        -h, --help  Shows this help

    Arguments:
        <user>  Full qualified target user id. Will error
                upon invalid id or if target isn't a member
                of this room.
    """

    name:    str       = "whitelist"
    aliases: List[str] = ["white", "w"]
    admin:   bool      = True


    async def __call__(self):
        add, dele = self.args.pop("add"), self.args.pop("del")
        user_str = self.args.pop("<user>") or ""
        user = self.room.state.members.get(user_str.lower(), None)

        if (add or dele) and not user:
            return await self.room.timeline.send(
                Notice("Specified user is not a member of this room"),
            )

        if add:
            self.markov_room.whitelist.add(user.user_id)
            await self.markov_room.save()
            return await self.room.timeline.send(
                Notice(f"Added {user.user_id} to whitelist"),
            )
        elif dele:
            self.markov_room.whitelist.discard(user.user_id)
            await self.markov_room.save()
            return await self.room.timeline.send(
                Notice(f"Removed {user.user_id} from whitelist"),
            )

        await self.room.timeline.send(
            Notice(
                "Current users in the whitelist:\n\n" +
                ("\n".join(self.markov_room.whitelist) or "None"),
            ),
        )
