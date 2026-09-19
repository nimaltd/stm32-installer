"""
Shared pieces for the IDE integrations.

Every integration edits a file the user cannot afford to lose. A corrupted
.cproject or .uvprojx means a project that will not open, and the user will not
connect that to having run an installer. So three rules hold everywhere:

1. Back the file up before touching it.
2. Bail out rather than guess. An integration that does not recognise the file
   reports what to do by hand and changes nothing.
3. Be idempotent. Installing twice must not add anything twice.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path

# Wraps what this tool adds to a text file, so it can be found again.
MARK_OPEN = "# >>> stm32-installer: {name} >>>"
MARK_CLOSE = "# <<< stm32-installer: {name} <<<"

CHANGED = "changed"
ALREADY = "already"
MANUAL = "manual"
SKIPPED = "skipped"


class Outcome:
    """What an integration did, and what the user still has to do themselves."""

    def __init__(self, ide, status, message, steps=None, backup=None):
        self.ide = ide
        self.status = status
        self.message = message
        self.steps = steps or []
        self.backup = backup

    @property
    def needs_user(self):
        return self.status == MANUAL

    def __repr__(self):
        return f"Outcome({self.ide}, {self.status})"


def backup(path):
    """
    Copy a file aside before editing it.

    Named with a timestamp rather than a plain .bak, so a second install does
    not overwrite the copy taken before the first one.
    """
    path = Path(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_suffix(path.suffix + f".{stamp}.bak")

    shutil.copyfile(path, target)

    return target


def relative(path, root):
    """
    A forward slash path from root to path, going up where it has to.

    Keil and IAR keep their project file in a subfolder such as MDK or EWARM,
    so the library sits above it and the answer has to start with "..".
    Path.relative_to cannot express that, which is why os.path.relpath is used.
    Falls back to an absolute path only when the two are on different drives.
    """
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(root).resolve())).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()
