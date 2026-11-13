#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""List the Python files the web page loads, in ``web/manifest.json``.

    python web/build_manifest.py

A static site cannot list a folder, so the page needs to be told which files
make up the package. Run this after adding or removing a module; a test fails
if the list is out of date.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def build():
    files = []
    for folder, _dirs, names in os.walk(os.path.join(ROOT, "eigenchip")):
        for name in sorted(names):
            if name.endswith(".py") and name not in ("cli.py", "__main__.py"):
                files.append(os.path.relpath(os.path.join(folder, name), ROOT).replace(os.sep, "/"))
    return {"package": sorted(files), "vendor": {"clio_synth.py": "web/vendor/clio/clio_synth.py"}}


if __name__ == "__main__":
    with open(os.path.join(HERE, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(build(), f, indent=1)
        f.write("\n")
    print("wrote web/manifest.json")
