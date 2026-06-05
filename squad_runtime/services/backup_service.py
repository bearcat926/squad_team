"""Backup and restore service for Squad Runtime projects.

Creates and restores tar.gz archives of a project's ``.squad`` directory,
with an option to exclude the authentication token by default.
"""

from __future__ import annotations

import os
import tarfile
from pathlib import Path


def backup(
    squad_dir: Path,
    output_path: Path,
    *,
    include_token: bool = False,
) -> Path:
    """Create a tar.gz archive of *squad_dir*.

    Parameters
    ----------
    squad_dir:
        The ``.squad`` directory to back up.
    output_path:
        Destination path for the ``.tar.gz`` file.
    include_token:
        When ``False`` (the default), ``.squad/token`` is excluded from the
        archive so that secrets are not leaked.

    Returns
    -------
    Path
        The resolved path of the created archive.
    """

    squad_dir = Path(squad_dir).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    token_rel = "token"

    with tarfile.open(output_path, "w:gz") as tar:
        for root, _dirs, files in os.walk(squad_dir):
            for filename in files:
                full_path = Path(root) / filename
                arcname = full_path.relative_to(squad_dir)

                # Skip token unless explicitly requested.
                if not include_token and str(arcname).replace("\\", "/") == token_rel:
                    continue

                tar.add(full_path, arcname=str(arcname))

    return output_path


def restore(backup_path: Path, target_dir: Path) -> Path:
    """Extract a backup archive into *target_dir*.

    Parameters
    ----------
    backup_path:
        Path to the ``.tar.gz`` backup file.
    target_dir:
        Directory to extract into.  Created if it does not exist.

    Returns
    -------
    Path
        The resolved *target_dir* after extraction.
    """

    backup_path = Path(backup_path).resolve()
    target_dir = Path(target_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(path=target_dir, filter="data")

    return target_dir
