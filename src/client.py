# File: client.py
# Author: vslg (slgf@protonmail.ch)
# Brief: Implements Matrix Client used in this project
# Date: 2021-04
# Copyright (c) 2021 vslg

from dataclasses import dataclass, field

from mio.client import Client
from mio.core.data import Runtime

from .module import MarkovModule


@dataclass
class MarkovClient(Client):
    markov: Runtime[MarkovModule] = field(init=False, repr=False)

    def __post_init__(self):
        self.markov = MarkovModule(self)
        super().__post_init__()
