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

"""Unit tests for the immutable version store."""

import pytest

from urdf_live_editor.model.robot_model import Link, RobotModel
from urdf_live_editor.model.version_store import model_diff, VersionStore


def _model(*link_names):
    """Return a model with the given (jointless) links."""
    model = RobotModel(name='r')
    for name in link_names:
        model.links[name] = Link(name)
    return model


def test_initial_version_recorded():
    """A new store holds exactly one version at index 0."""
    store = VersionStore(_model('a'))
    assert len(store) == 1
    assert store.current.index == 0
    assert store.current.parent is None


def test_commit_appends_version():
    """Committing a model appends a child version."""
    store = VersionStore(_model('a'))
    version = store.commit(_model('a', 'b'))
    assert version.index == 1
    assert version.parent == 0
    assert store.current.model.link_names() == ['a', 'b']


def test_stored_model_is_isolated():
    """Mutating a model after commit does not change the stored snapshot."""
    model = _model('a')
    store = VersionStore(model)
    model.links['late'] = Link('late')
    assert store.current.model.link_names() == ['a']


def test_rollback_appends_restored_version():
    """Rollback appends a new version equal to the target's model."""
    store = VersionStore(_model('a'))
    store.commit(_model('a', 'b'))
    restored = store.rollback(0)
    assert restored.index == 2
    assert restored.label == 'rollback to v0'
    assert store.current.model.link_names() == ['a']
    assert len(store) == 3


def test_get_out_of_range_raises():
    """Requesting a missing version index raises IndexError."""
    store = VersionStore(_model('a'))
    with pytest.raises(IndexError):
        store.get(5)


def test_audit_log_reports_diffs():
    """The audit log carries a diff against each version's parent."""
    store = VersionStore(_model('a'))
    store.commit(_model('a', 'b'))
    log = store.audit_log()
    assert log[0]['diff'] is None
    assert log[1]['diff']['added_links'] == ['b']


def test_model_diff_detects_changes():
    """model_diff reports added/removed links and joints."""
    diff = model_diff(_model('a'), _model('a', 'b'))
    assert diff['added_links'] == ['b']
    assert diff['removed_links'] == []
