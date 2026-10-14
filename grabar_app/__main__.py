import sys
import traceback


def main() -> None:
    if "--cli" in sys.argv or "cli" in sys.argv[1:]:
        from .cli import main as run
    else:
        from .gui import main as run
    run()


try:
    main()
except Exception:
    # Con pythonw.exe (sin consola) los errores se perderían: se guardan en logs/error.log
    from pathlib import Path

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
    try:
        import tkinter
        from tkinter import messagebox

        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Error al iniciar", f"{traceback.format_exc()[-1500:]}\n\nDetalle en: {log_dir / 'error.log'}")
    except Exception:
        pass
    raise
