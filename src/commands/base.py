# File: base.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Base classes for commands
# Date: 2021-04
# Copyright (c) 2021 vslg & contributors

from collections import Mapping
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Dict, Iterator, List, Type, Union

import docopt
from mio.client import Client
from mio.core.contents import EventContent
from mio.rooms.contents.messages import Notice
from mio.rooms.events import TimelineEvent
from mio.rooms.room import Room
from mio.rooms.user import RoomUser
from mistune import markdown

from ..module import MarkovRoom


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

    args:    Dict[str, Any] = field(init=False)
    sender:  RoomUser       = field(init=False)
    content: EventContent   = field(init=False)
    client:  Client         = field(init=False)

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

        self.sender  = self.room.state.members[self.event.sender]
        self.content = self.event.content
        self.client  = self.room.client


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
