#
# OpenVMP, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#

from abc import ABC, abstractmethod
import copy

from .. import logging as pc_logging


class Test(ABC):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def test(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        raise NotImplementedError("This method should be overridden")

    async def test_log_wrapper(self, tests_to_run: list["Test"], ctx, shape, test_ctx: dict = {}) -> bool:
        test_ctx = copy.copy(test_ctx)
        test_ctx["log_wrapper"] = True
        action_name = (
            shape.project_name
            if "action_prefix" not in test_ctx
            else f"{test_ctx['action_prefix']}:{shape.project_name}"
        )
        with pc_logging.Action("Test", action_name, shape.name, self.name):
            return await self.test(tests_to_run, ctx, shape, test_ctx)

    def _log_message_prepare(self, *args) -> str:
        if args:
            message = args[0] % args[1:] if args[1:] else args[0]
            message = f": {message}"
        else:
            message = ""
        return message

    def debug(self, shape, *args) -> None:
        """This methods works like logging.debug() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test: {shape.project_name}:{shape.name}: {self.name}{message}")

    def failed(self, shape, *args) -> None:
        """This methods works like logging.error() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.error(f"Test failed: {shape.project_name}:{shape.name}: {self.name}{message}")

    def passed(self, shape, *args) -> None:
        """This methods works like logging.error() but prepends the message with the test name and the shape name."""
        message = self._log_message_prepare(*args)
        pc_logging.debug(f"Test passed: {shape.project_name}:{shape.name}: {self.name}{message}")
