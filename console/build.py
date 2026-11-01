#!/usr/bin/env python3
"""Build the single self-contained Elaria console shell.

Assembles src/shell.css + src/shell.html + src/shell.js together with the vendored
three.js r128 and the Elaria visualizer engine into ONE index.html with zero external
references, so it renders in a sandboxed preview with no network and runs from file://.

    python3 build.py            # writes index.html next to this script
"""
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def read(*parts):
    with open(os.path.join(HERE, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def inline(name, body):
    """A literal </script> inside inlined JS would close the tag early. Refuse rather than corrupt."""
    low = body.lower()
    if "</script" in low:
        sys.exit(f"REFUSING TO BUILD: {name} contains a literal </script sequence")
    return f"<script>\n{body}\n</script>"


def gate_glsl(path):
    """An undeclared uniform in GLSL compiles to nothing: three.js logs to the console and the mesh
    draws no pixels, so the whole orb vanishes with no JS error anywhere. node --check cannot see it.
    Resolve each shader's concatenated source (PAL / VERT_COMMON prefixes included) and refuse to
    build if any uXxx identifier is used without a 'uniform ... uXxx' declaration in that same shader.
    This gate exists because v6.2 shipped exactly that bug and the owner saw an empty stage."""
    import re

    with open(path, encoding="utf-8") as source:
        text = source.read()
    shaders = {}
    for m in re.finditer(r"var\s+([A-Z][A-Z0-9_]*)\s*=\s*((?:[A-Z][A-Z0-9_]*\s*\+\s*'\\n'\s*\+\s*)?\[[\s\S]*?\]\.join\('\\n'\);)", text):
        shaders[m.group(1)] = m.group(2)
    if not shaders:
        sys.exit(f"REFUSING TO BUILD: no shaders found in {path} — the gate's parser is out of date")

    def strings_of(name, seen=()):
        if name in seen or name not in shaders:
            return []
        rhs = shaders[name]
        prefixes = re.findall(r"\b([A-Z][A-Z0-9_]*)\s*\+\s*'\\n'", rhs)
        own = re.findall(r"'((?:[^'\\]|\\.)*)'", rhs)
        out = []
        for pfx in prefixes:
            out += strings_of(pfx, seen + (name,))
        return out + own

    bad = []
    for name in [n for n in shaders if n.endswith(("VERT", "FRAG"))]:
        src = "\n".join(strings_of(name))
        used = set(re.findall(r"\bu[A-Z]\w*", src))
        declared = set(re.findall(r"uniform\s+\w+\s+(u\w+)", src))
        for u in sorted(used - declared):
            bad.append(f"{name} uses {u} without declaring it")
    if bad:
        sys.exit("REFUSING TO BUILD: undeclared GLSL uniforms in {}\n  {}".format(path, "\n  ".join(bad)))
    print(f"  gate  {path.split('/')[-1]}: {len(shaders)} shaders, every uniform declared")


def gate_js(path):
    """A syntax error inside an inlined <script> kills the whole shell silently in the browser.
    Check it here, where it is loud. Skipped only if node is not installed."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        print("  WARN  node not found - skipping the JS syntax gate")
        return
    r = subprocess.run([node, "--check", path], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        sys.exit(f"REFUSING TO BUILD: {path} has a syntax error\n{r.stderr.strip()}")
    print(f"  gate  {os.path.basename(path)} parses clean")


# OWNER'S RULING, 2026-11-02, verbatim: "stop trying to learn from what I sent u just implement it
# verbatim as is thstts bbeen the problem from the start". The engine below this pin is the maker's
# final file, byte-identical. No owner layer, no improvements, no interpretations. Update this pin
# ONLY when the owner hands over a new maker file — never to smuggle an edit through.
ENGINE_SHA = "5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447"


def gate_verbatim(path):
    with open(path, "rb") as fh:
        got = hashlib.sha256(fh.read()).hexdigest()
    if got != ENGINE_SHA:
        sys.exit(
            "REFUSING TO BUILD: gate_verbatim failed.\n"
            "  elaria-visualizer.js is NOT the maker's file byte-identical.\n"
            f"  expected sha256 {ENGINE_SHA}\n"
            f"  got      sha256 {got}\n"
            "  ruling 2026-11-02: implement it verbatim, as is. Revert the edit, or update\n"
            "  ENGINE_SHA only when the owner hands over a new maker file."
        )
    print("  gate  engine is the maker's final file verbatim (sha256 pinned)")


def main():
    for f in (("src", "shell.js"), ("elaria-visualizer.js",), ("vendor", "three.min.js")):
        gate_js(os.path.join(HERE, *f))
    gate_verbatim(os.path.join(HERE, "elaria-visualizer.js"))
    gate_glsl(os.path.join(HERE, "elaria-visualizer.js"))

    css = read("src", "shell.css")
    markup = read("src", "shell.html")
    js = read("src", "shell.js")
    three = read("vendor", "three.min.js")
    engine = read("elaria-visualizer.js")

    doc = (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="dark">\n'
        "<title>Elaria</title>\n"
        "<!--\n"
        "  Elaria console shell v6 - one self-contained file.\n"
        "  zero external references, zero network calls, no api key touched.\n"
        "  three.js r128 (MIT) and the Elaria visualizer engine are inlined below.\n"
        "  built by build.py from src/shell.css + src/shell.html + src/shell.js.\n"
        "-->\n"
        "<style>\n" + css + "\n</style>\n"
        "</head>\n<body>\n" + markup + "\n"
        + inline("three.min.js", three) + "\n"
        + inline("elaria-visualizer.js", engine) + "\n"
        + inline("shell.js", js) + "\n"
        "</body>\n</html>\n"
    )

    out = os.path.join(HERE, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)

    blob = doc.encode("utf-8")
    print(f"built {out}")
    print(f"  bytes        {len(blob)} ({len(blob) / 1024:.1f} KiB)")
    print(f"  sha256       {hashlib.sha256(blob).hexdigest()[:16]}")
    print(f"  three.js     {len(three.encode('utf-8'))} bytes inlined")
    print(f"  engine       {len(engine.encode('utf-8'))} bytes inlined")
    print(f"  shell js     {len(js.encode('utf-8'))} bytes inlined")
    print(f"  css          {len(css.encode('utf-8'))} bytes inlined")


if __name__ == "__main__":
    main()
