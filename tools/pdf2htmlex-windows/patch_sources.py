"""
Source fixes needed for a MinGW-w64 build of pdf2htmlEX 0.18.8.rc1.
Each edit is idempotent and fails loudly if its anchor text is missing.
"""
import pathlib
import sys

work = pathlib.Path(sys.argv[1])


def edit(rel: str, old: str, new: str) -> None:
    path = work / rel
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"anchor not found in {rel}: {old[:60]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {rel}")


# 1. POSIX sigaction() does not exist on Windows: use signal() for the crash
#    handler (SIGBUS/SIGSYS do not exist there either).
edit("pdf2htmlEX/src/util/SignalHandler.cc",
     "struct sigaction act;",
     "#ifndef _WIN32\nstruct sigaction act;\n#endif")
edit("pdf2htmlEX/src/util/SignalHandler.cc",
     """  memset(&act, 0, sizeof(act));
  act.sa_handler = signalHandler;""",
     """#ifdef _WIN32
  signal(SIGILL,  signalHandler);
  signal(SIGFPE,  signalHandler);
  signal(SIGSEGV, signalHandler);
#else
  memset(&act, 0, sizeof(act));
  act.sa_handler = signalHandler;""")
edit("pdf2htmlEX/src/util/SignalHandler.cc",
     "  sigaction(SIGSYS,  &act, NULL);  // Bad system call (SVr4)",
     "  sigaction(SIGSYS,  &act, NULL);  // Bad system call (SVr4)\n#endif")

# 2. Windows system libraries used by static Poppler/FontForge/GLib.
edit("pdf2htmlEX/CMakeLists.txt",
     "  -lz\n  -lm\n)",
     "  -lz\n  -lm\n  -lintl\n  -liconv\n  -lgdi32\n  -ladvapi32\n  -lshell32\n  -lole32\n  -lws2_32\n)")
