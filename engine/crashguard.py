"""Makes failures visible: writes `crash.log` next to the client (traceback, Python/SDL info, faulthandler dump for hard crashes) and, on Windows or when
started from a double-click, waits for Enter so the console window does not vanish."""
import faulthandler, os, platform, sys, time, traceback

HERE = os.path.dirname(os.path.abspath(__file__)); LOG = os.path.join(os.path.dirname(HERE), "crash.log")   # crash.log in the project folder
_fh = None

def _write(text):
    try:
        with open(LOG, "a", encoding="utf-8") as f: f.write(text)
    except OSError: pass

def header():
    return "==== %s  Python %s (%s)  %s ====\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), sys.version.split()[0], platform.architecture()[0], platform.platform())

def note(what):
    """Log the exception being handled (call from an `except` block)."""
    _write(header() + what + "\n" + traceback.format_exc() + "\n")

def run(main):
    global _fh
    try: _fh = open(LOG, "a", encoding="utf-8"); _fh.write(header() + "start\n"); _fh.flush(); faulthandler.enable(file=_fh, all_threads=True)
    except OSError: pass
    try: main()
    except SystemExit: raise
    except KeyboardInterrupt: pass
    except BaseException:
        tb = traceback.format_exc(); _write(header() + "CRASH\n" + tb + "\n"); print("\n" + tb); print("The error is saved in", LOG)
        if sys.platform == "win32" or os.environ.get("GRAAL_PAUSE"):
            try: input("Press Enter to close...")
            except EOFError: pass
        sys.exit(1)
