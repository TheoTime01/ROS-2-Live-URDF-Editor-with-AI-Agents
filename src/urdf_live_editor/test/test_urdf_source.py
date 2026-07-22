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

"""Unit tests for the URDF source loader and change detection."""

from urdf_live_editor.urdf_source_node import UrdfSource

FIRST = '<robot name="r"><link name="a"/></robot>'
SECOND = '<robot name="r"><link name="a"/><link name="b"/></robot>'


def _write(path, text):
    """Write ``text`` to ``path``."""
    with open(path, 'w') as handle:
        handle.write(text)


def test_load_returns_file_contents(tmp_path):
    """A plain .urdf file loads as its own text."""
    path = str(tmp_path / 'model.urdf')
    _write(path, FIRST)
    source = UrdfSource(path)
    assert source.load().strip() == FIRST


def test_unchanged_file_is_not_reloaded(tmp_path):
    """An unchanged file makes poll return None."""
    path = str(tmp_path / 'model.urdf')
    _write(path, FIRST)
    source = UrdfSource(path)
    source.load()
    assert not source.has_changed()
    assert source.poll() is None


def test_edit_triggers_reload_and_callback(tmp_path):
    """Editing the file makes poll reload and notify callbacks."""
    path = str(tmp_path / 'model.urdf')
    _write(path, FIRST)
    source = UrdfSource(path)
    seen = []
    source.on_change(seen.append)
    source.load()

    _write(path, SECOND)
    assert source.has_changed()
    reloaded = source.poll()
    assert reloaded.strip() == SECOND
    assert len(seen) == 1
    assert seen[0].strip() == SECOND
