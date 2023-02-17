# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#
import os
import random
from typing import Any, Callable, Optional

import requests


class AzureSlurmError(RuntimeError):
    pass


def custom_chaos_mode(action: Callable) -> Callable:
    def wrapped(func: Callable) -> Any:
        return chaos_mode(func, action)

    return wrapped


def chaos_mode(func: Callable, action: Optional[Callable] = None) -> Callable:
    def default_action() -> Any:
        raise random.choice(
            [RuntimeError, ValueError, requests.exceptions.ConnectionError]
        )("Random failure")

    action = action or default_action

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if is_chaos_mode():
            return action or default_action()

        return func(*args, **kwargs)

    return wrapped


def is_chaos_mode() -> bool:
    return random.random() < float(os.getenv("AZURE_SLURM_CHAOS_MODE", 0))
