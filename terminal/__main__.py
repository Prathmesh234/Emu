"""Entry point: python -m terminal"""

import click

from terminal.config import load_config
from terminal.app import EmuTerminalApp


@click.command()
@click.option("--backend", default="http://127.0.0.1:8000", help="Backend URL")
@click.option("--token", default=None, help="Auth token (reads .emu/.auth_token if omitted)")
def main(backend: str, token: str | None):
    """Launch the Emu terminal UI."""
    cfg = load_config(backend_url=backend, token_override=token)
    app = EmuTerminalApp(cfg)
    app.run()


if __name__ == "__main__":
    main()
