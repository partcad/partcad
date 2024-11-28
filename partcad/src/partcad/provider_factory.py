#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.
#

from . import factory
from .provider import Provider


class ProviderFactory(factory.Factory):
    provider: Provider
    name: str
    orig_name: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config: object,
    ):
        super().__init__()

        self.ctx = ctx
        self.project = source_project
        self.config = config

        self.target_project = target_project
        self.name = config["name"]
        self.orig_name = config["orig_name"]

    def _create_provider(self, config: object) -> Provider:
        provider = Provider(config)
        provider.name = f"{self.target_project.name}:{self.name}"
        provider.config = self.config
        provider.project_name = self.target_project.name  # TODO(clairbee): pass it via the constructor
        # TODO(clairbee): Make the next line work for provider_factory_file only
        provider.info = lambda: self.info(provider)
        return provider

    def _create(self, config: object):
        self.provider = self._create_provider(config)
        if hasattr(self, "path"):
            self.provider.path = self.path

        self.target_project.providers[self.name] = self.provider
        self.ctx.stats_providers += 1
