# File: image.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Commands related to image manipulation
# Date: 2021-07
# Copyright (c) 2021 vslg

from io import BytesIO
from typing import List
from asyncio import ensure_future

from mio.media.store import MediaStore
from mio.rooms.contents.messages import Image, Notice
from wand.image import Image as WImage

from .base import MarkovCommand
from .general import RootCommand


@RootCommand.add
class SwirlCommand(MarkovCommand):
    """Swirls an image

    Reply to an image and I'll swirl it for you.

    Usage:
        swirl [<angle>]
        swirl -h | --help

    Options:
        -h, --help  Shows this help

    Arguments:
        <angle>  Specified angle [default: 120]
    """

    name:    str       = "swirl"
    aliases: List[str] = ["sw"]

    async def __call__(self):
        image_id = self.event.content.in_reply_to

        if not image_id:
            return await self.room.timeline.send(
                Notice("Please reply to an image"),
            )

        if image_id not in self.room.timeline:
            return await self.room.timeline.send(
                Notice("I cannot see this event"),
            )

        image: Image = self.room.timeline[image_id].content

        if not issubclass(image.__class__, Image):
            return await self.room.timeline.send(
                Notice("Please reply to an image"),
            )

        ensure_future(self.download_and_send(image))


    async def download_and_send(self, image: Image) -> None:
        try:
            await self.client.media.download(image.mxc)
        except Exception as e:
            print(e)
            return await self.room.timeline.send(
                Notice("Error while downloading media"),
            )

        store: MediaStore = self.client.media
        image_path        = await store._mxc_path(image.mxc).resolve()

        with WImage(filename=image_path) as img:
            img.swirl(degree=-120)

            blob  = BytesIO(img.make_blob())
            media = await Image.from_data(self.client, blob)
            await self.room.timeline.send(media)

