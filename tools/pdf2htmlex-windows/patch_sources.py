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
     "add_executable(pdf2htmlEX ${PDF2HTMLEX_SRC})",
     "if(WIN32)\n  set(PDF2HTMLEX_LIBS ${PDF2HTMLEX_LIBS} -lintl -liconv -lgdi32 -ladvapi32 -lshell32 -lole32 -lws2_32)\n  # Windows default stack is 2 MB (Linux: 8 MB): deep Poppler recursion on\n  # large documents overflowed it\n  set(CMAKE_EXE_LINKER_FLAGS \"${CMAKE_EXE_LINKER_FLAGS} -Wl,--stack,67108864\")\nendif()\n"
     "add_executable(pdf2htmlEX ${PDF2HTMLEX_SRC})")

# 3. Poppler 0.89 glib: recent GLib/GCC reject g_once_init_* on a volatile
#    variable (fixed upstream in later Poppler releases the same way).
edit("poppler/glib/poppler-private.h",
     "static volatile gsize g_define_type_id__volatile = 0;",
     "static gsize g_define_type_id__volatile = 0;")

# 4. FontForge 20200314 headers include <gio/gio.h>: add the GLib/GIO include
#    directories explicitly (the upstream file relied on them being implicit).
edit("pdf2htmlEX/CMakeLists.txt",
     "find_package(PkgConfig)\n",
     "find_package(PkgConfig)\npkg_check_modules(GIO REQUIRED gio-2.0 glib-2.0)\ninclude_directories(${GIO_INCLUDE_DIRS})\n")

# 5. Report which signal crashed the process (the upstream handler omits it).
edit("pdf2htmlEX/src/util/SignalHandler.cc",
     "  write(STDERR_FILENO, oopsMessage,        strlen(oopsMessage) );",
     "  write(STDERR_FILENO, oopsMessage,        strlen(oopsMessage) );\n"
     "  { char sigBuf[48]; int n = snprintf(sigBuf, sizeof(sigBuf), \"Signal: %d\\n\", sigInt);\n"
     "    if (n > 0) write(STDERR_FILENO, sigBuf, (size_t)n); }")
