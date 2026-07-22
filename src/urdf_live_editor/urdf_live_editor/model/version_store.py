# Copyright 2026 theotime01
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Immutable version store with rollback for applied model changes.

Every accepted edit appends a new :class:`Version` — a frozen snapshot of the
model plus the operations that produced it and a diff against its parent.
History is append-only: a rollback does not delete anything, it appends a fresh
version whose model equals an earlier one, so the audit trail is complete and
every prior state remains recoverable.
"""

from dataclasses import dataclass, field
import time
from typing import Optional, Tuple

from urdf_live_editor.model.robot_model import RobotModel


def model_diff(before, after):
    """Return the added/removed/changed links and joints between two models."""
    before_links, after_links = set(before.links), set(after.links)
    before_joints, after_joints = set(before.joints), set(after.joints)
    changed = [
        name for name in before_joints & after_joints
        if before.joints[name] != after.joints[name]]
    return {
        'added_links': sorted(after_links - before_links),
        'removed_links': sorted(before_links - after_links),
        'added_joints': sorted(after_joints - before_joints),
        'removed_joints': sorted(before_joints - after_joints),
        'changed_joints': sorted(changed),
    }


@dataclass(frozen=True)
class Version:
    """An immutable snapshot of the model at one point in its history."""

    index: int
    model: RobotModel
    label: str
    parent: Optional[int]
    operations: Tuple[dict, ...] = ()
    timestamp: float = field(default_factory=time.time)

    def to_urdf(self):
        """Serialize this version's model to a URDF string."""
        return self.model.to_string()


class VersionStore:
    """Append-only history of model versions with rollback."""

    def __init__(self, model, label='initial'):
        """Seed the store with an initial version of ``model``."""
        self._versions = []
        self._append(model, label, parent=None, operations=())

    def _append(self, model, label, parent, operations):
        """Append a snapshot as a new version and return it."""
        version = Version(
            index=len(self._versions),
            model=model.copy(),
            label=label,
            parent=parent,
            operations=tuple(operations))
        self._versions.append(version)
        return version

    @property
    def current(self):
        """Return the most recent version."""
        return self._versions[-1]

    def current_model(self):
        """Return an editable copy of the current model."""
        return self.current.model.copy()

    def get(self, index):
        """Return the version at ``index``, raising ``IndexError`` if absent."""
        if index < 0 or index >= len(self._versions):
            raise IndexError('no version with index %d' % index)
        return self._versions[index]

    def commit(self, model, operations=(), label=None):
        """Append ``model`` as a new version and return it."""
        parent = self.current.index
        if label is None:
            label = 'edit %d' % (parent + 1)
        return self._append(model, label, parent=parent, operations=operations)

    def rollback(self, target_index):
        """Restore an earlier version by appending a copy of it."""
        target = self.get(target_index)
        label = 'rollback to v%d' % target_index
        return self._append(
            target.model, label, parent=self.current.index, operations=())

    def history(self):
        """Return the full list of versions, oldest first."""
        return list(self._versions)

    def audit_log(self):
        """Return one audit entry per version, each with a diff to its parent."""
        entries = []
        for version in self._versions:
            if version.parent is None:
                diff = None
            else:
                diff = model_diff(
                    self._versions[version.parent].model, version.model)
            entries.append({
                'index': version.index,
                'label': version.label,
                'parent': version.parent,
                'operations': list(version.operations),
                'diff': diff,
                'timestamp': version.timestamp,
            })
        return entries

    def __len__(self):
        """Return the number of versions recorded so far."""
        return len(self._versions)
