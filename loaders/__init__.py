"""Loader abstraction classes for Minecraft modloaders"""
from loaders.neoforge import NeoForgeLoader
from loaders.forge import ForgeLoader
from loaders.fabric import FabricLoader

__all__ = ["NeoForgeLoader", "ForgeLoader", "FabricLoader"]
