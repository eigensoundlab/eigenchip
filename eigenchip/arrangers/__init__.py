# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Daniel Sandner
"""Arrangers: interchangeable strategies for reducing a Grid to a few voices.

Every arranger is a module with ``NAME``, ``SUMMARY`` and
``arrange(grid, voices=3) -> Arrangement``. Add a module, list it here, and it
shows up in the command line and in the results table.
"""
from __future__ import annotations

from . import expand, roles, roles_arp, skyline

ARRANGERS = {m.NAME: m for m in (skyline, roles, roles_arp, expand)}
DEFAULT = "roles-arp"


def arrange(grid, name=DEFAULT, voices=3, **how):
    """``how`` is passed on to arrangers that take more than a number of voices (``expand``: style, chords_given)."""
    if name not in ARRANGERS:
        raise ValueError("Unknown arranger '%s'. Available: %s" % (name, ", ".join(ARRANGERS)))
    return ARRANGERS[name].arrange(grid, voices, **how)
