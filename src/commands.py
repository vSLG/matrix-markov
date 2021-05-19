# File: commands.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Implements bot's commands
# Date: 2021-04
# Copyright (c) 2021 vslg & contributors

from collections import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Dict, Iterator, List, Type, Union

import docopt
from mio.rooms.contents.messages import Notice
from mio.rooms.events import TimelineEvent
from mio.rooms.room import Room
from mio.rooms.user import RoomUser
from mistune import markdown

from .module import MarkovRoom


class DocoptExit(Exception):
    usage = ""

    def __init__(self, message = ""):
        self.message = message


docopt.DocoptExit = DocoptExit


class Command(Mapping[str, Type["Command"]]):
    """A Command can be a standalone command or a command with subcommands.

    The command's behavior should be defined in Command.__call__()

    If it holds any subcommands, they should be added to _data and _aliases.
    """

    # These fields are only for subcommands
    _data:    Mapping[str, Type["Command"]] = {}
    _aliases: Mapping[str, Type["Command"]] = {}

    # Actual command info
    name:    str       = ""
    aliases: List[str] = []


    def __getitem__(self, key: str) -> Type["Command"]:
        return self._data[key]


    def __iter__(self) -> Iterator[str]:
        return iter(self._data)


    def __len__(self) -> int:
        return len(self._data)


    @classmethod
    def add(cls, command):
        cls._data[command.name] = command

        for alias in command.aliases:
            cls._aliases[alias] = command

        return command


@dataclass
class MarkovCommand(Command):
    """Base class for every command of this bot.

    Commands syntax is parsed by docopt, commands are check permissions before
    executed (see add method below), aliases and subcommands are added
    automatically to __doc__.
    """

    argv:        Union[str, List[str]] = field()
    room:        Room                  = field()
    event:       TimelineEvent         = field()
    markov_room: MarkovRoom            = field()

    args:   Dict[str, Any] = field(init=False)
    sender: RoomUser       = field(init=False)

    admin: bool = False


    def __post_init__(self):
        # If we have subcommands, add a "Commands" section to __doc__
        if self._data:
            user_commands  = filter(lambda f: not f.admin, self._data.values())
            admin_commands = filter(lambda f: f.admin, self._data.values())

            for (kind, commands) in [
                ("User", user_commands), ("Admin", admin_commands),
            ]:
                self.__doc__ += f"\n{kind} commands:\n"

                cmds = [(
                    "    %s,%s" % (cmd.name, ",".join(cmd.aliases)),
                    cmd.__doc__.split("\n")[0],
                ) for cmd in commands]

                # Alignment is always good
                offset = max(map(lambda f: len(f[0]), cmds)) + 2

                for name, desc in cmds:
                    self.__doc__ += f"    %-{offset}s{desc}\n" % name

        # If we have aliases, add them to "Aliases" section of __doc__
        if self.aliases:
            self.__doc__ += f"\nAliases:\n{' '*8}{', '.join(self.aliases)}"

        try:
            self.args = docopt.docopt(
                self.__doc__,
                options_first = True,
                argv          = self.argv,
                help          = False,
            )
        except DocoptExit:
            self.args = None

        self.sender = self.room.state.members[self.event.sender]


    async def __call__(self):
        """ This function will look for subcommands specified by <command> arg.
        Only call this function in subclasses that have subcommands.

        An example is RootCommand below.
        """

        try:
            cmd_name = self.args.get("<command>", None)
            cmd_args = self.args.get("<args>", []) or []

            aliased_cmd = self._aliases.get(cmd_name, None)
            cmd         = aliased_cmd or self._data.get(cmd_name, None)

            if not cmd:
                return await self.help("Invalid command")

            await cmd(cmd_args, self.room, self.event, self.markov_room)()
        except AttributeError:
            await self.help("Invalid usage")


    async def help(self, extra_msg: str = "", usage_only: bool = True) -> None:
        body = ""

        if extra_msg:
            body += f"{extra_msg}\n\n"

        # Get rid of extra indentation
        doc = getattr(self, "__doc__", "").replace("\n    ", "\n").strip()

        body += "```\n"
        if usage_only:
            body += docopt.printable_usage(doc)
        else:
            body += doc
        body += "\n```"

        message                = Notice(body)
        message.formatted_body = markdown(body)
        message.format         = "org.matrix.custom.html"

        await self.room.timeline.send(message)


    @classmethod
    def add(cls, command):
        """Adds a subcommand to this command.

        We wrap the command's __call__ to check if the sender has enough perms
        for running this command and display help if solicited.
        """

        # We need to clear _data and _aliases because they're inherited
        command._data    = {}
        command._aliases = {}

        @super().add
        @wraps(command, updated=())
        class Wrapper(command):
            async def __call__(self):
                if (
                    type(self).admin and not (
                        self.sender.user_id in self.markov_room.whitelist or
                        self.sender.power_level == 100
                    )
                ):
                    return await self.room.timeline.send(
                        Notice("You do not have permission to run this "
                               "command."))

                if not self.args:
                    return await super().help("Invalid usage")

                command = self.args.get("<command>", "")
                command = (command or "").lower()

                if self.args["--help"] or command == "help" or command == "h":
                    return await super().help(usage_only=False)

                return await super().__call__()


        return Wrapper


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
