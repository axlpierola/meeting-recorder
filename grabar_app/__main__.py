import sys


def main() -> None:
    if "--cli" in sys.argv or "cli" in sys.argv[1:]:
        from .cli import main as run
    else:
        from .gui import main as run
    run()


main()
