"""Production entrypoint: aiohttp server (API+webhooks+panel) + APScheduler.

Run with: python -m mirza.server
"""
from __future__ import annotations

import logging

from aiohttp import web


async def _on_startup(app: web.Application) -> None:
    import mirza.plugins
    mirza.plugins.load_builtin_plugins()
    from mirza.jobs.scheduler import build_scheduler
    bot = app.get("bot")
    sched = build_scheduler(bot)
    app["scheduler"] = sched
    sched.start()
    logging.getLogger(__name__).info("scheduler started")


async def _on_cleanup(app: web.Application) -> None:
    sched = app.get("scheduler")
    if sched:
        sched.shutdown(wait=False)
    from mirza.db import dispose_engine
    await dispose_engine()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from mirza.api import make_app
    app = make_app()
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    port = int(__import__("os").environ.get("MIRZA_PORT", "8080"))
    web.run_app(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
