"""
Registering an installed library with whatever IDE the project uses.

A project can be more than one thing at once. A CubeMX project that also emits
CMake is both a CubeIDE project and a CMake project, and a user may build it
either way, so every integration that recognises the project runs.

Copying the files always succeeds. Registering them with an IDE may not, and a
failure there is reported rather than raised: the library is on disk either way,
and the user can finish by hand from the steps printed.
"""

from . import cmake, cubeide, iar, keil
from .base import ALREADY, CHANGED, MANUAL, SKIPPED, Outcome

BACKENDS = (cmake, cubeide, keil, iar)

__all__ = ["ALREADY", "CHANGED", "MANUAL", "SKIPPED", "Outcome", "detect", "integrate"]


def detect(project_root):
    """
    Every IDE that recognises this project.

    Returns a list of (backend, path) pairs, empty when nothing is recognised.
    """
    found = []

    for backend in BACKENDS:
        try:
            path = backend.detect(project_root)
        except OSError:
            continue

        if path is not None:
            found.append((backend, path))

    return found


def integrate(project_root, library, destination, only=None):
    """
    Register a library with every IDE found in the project.

    Args:
        project_root: the user's project.
        library: the Manifest that was installed.
        destination: the folder the library was installed into.
        only: restrict to one IDE by name, for example "cmake". None means all.

    Returns:
        A list of Outcome, one per IDE. Empty when no IDE was recognised.
    """
    outcomes = []

    for backend, path in detect(project_root):
        if only and backend.__name__.rsplit(".", 1)[-1] != only:
            continue

        try:
            outcomes.append(backend.integrate(path, library, destination, project_root))
        except Exception as error:
            # An integration must never take the install down with it. The files
            # are already copied, and the user can finish the job by hand.
            outcomes.append(
                Outcome(
                    backend.NAME,
                    MANUAL,
                    f"Could not update the project automatically: {error}",
                    getattr(backend, "_manual_steps", lambda *_: [])(
                        str(destination.name if hasattr(destination, "name") else destination)
                    ),
                )
            )

    return outcomes
