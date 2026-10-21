"""Cloudflare Pages integration for Marvin — site build and deploy status, build logs, deployments."""

from .provider import CloudflarePagesProvider

__all__ = ["CloudflarePagesProvider"]
__version__ = "0.4.0"
