import json
import asyncio
from enum import Enum
from abc import ABC, abstractmethod

from ..project import Project
from ..context import Context
from .. import logging as pc_logging
from partcad.cache_hash import CacheHash


def semaphore_wrapper(f):
    async def wrapper(*args, **kwargs):
        if Linting.semaphore is None:
            Linting.semaphore = asyncio.Semaphore(Linting.MAX_CONCURRENT_CHECKS)
        async with Linting.semaphore:
            return await f(*args, **kwargs)

    return wrapper

class Severity(Enum):
    FAILED = 1
    WARNING = 2

class LintingReport:
    def __init__(self, package: str) -> None:
        self.cached = False
        self.package = package
        self.messages: list[tuple[Severity, str]] = []

    def add(self, level: Severity, message: str) -> None:
        self.messages.append((level, message))

    def to_dict(self) -> dict:
        return {
            "package": self.package,
            "messages": [[level.value, message] for level, message in self.messages],
        }

    @staticmethod
    def from_dict(data: dict, from_cache: bool = True) -> "LintingReport":
        report = LintingReport(data["package"])
        report.cached = from_cache
        for level, message in data["messages"]:
            report.add(Severity(level), message)
        return report


class Linting(ABC):
    semaphore = None
    MAX_CONCURRENT_CHECKS = None

    def __init__(self, name: str) -> None:
        self.name = name

    @abstractmethod
    async def validate(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        raise NotImplementedError("This method should be overridden")

    @abstractmethod
    def get_targets(self, ctx: Context, package: Project) -> list[str]:
        raise NotImplementedError("This method should be overridden")

    def get_hash(self, name: str, target: str) -> CacheHash:
        hash = CacheHash(name, cache=True)
        hash.add_filename(target)
        hash.add_string(name)
        return hash

    @semaphore_wrapper
    async def validate_cached(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> LintingReport:
        cache_key = f"lint.{self.name}"
        hash = self.get_hash(package.name, target)
        cached_results = await ctx.cache_lints.read_data_async(hash, [cache_key])
        cached_bytes = cached_results.get(cache_key, [])
        if cached_bytes is not None and len(cached_bytes) > 0:
            result = json.loads(cached_bytes.decode())
            return LintingReport.from_dict(result)

        result: LintingReport = await self.validate(ctx, package, target, lint_ctx)

        await ctx.cache_lints.write_data_async(
          hash,
          {
            cache_key: json.dumps(result.to_dict()).encode()
          }
        )

        return result

    async def lint_log_wrapper(self, ctx: Context, package: Project, target: str, lint_ctx: dict = {}) -> None:
        with pc_logging.Action(self.name, package.name, target):
            result = await self.validate_cached(ctx, package, target, lint_ctx)
        self.report(result)

    def warning(self, package: str, message: str) -> None:
        pc_logging.warning(f"{self.name} Lint: {package}: {message}")

    def failed(self, package: str, message: str) -> None:
        pc_logging.error(f"{self.name} Lint: {package}: {message}")

    def report(self, result: LintingReport) -> None:
        for level, message in result.messages:
            if level == Severity.FAILED:
                self.failed(result.package, message)
            else:
                self.warning(result.package, message)
