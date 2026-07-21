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

"""Smoke test that the package and its submodules import cleanly."""

import importlib

import urdf_live_editor


def test_package_has_version():
    """The top-level package exposes a version string."""
    assert isinstance(urdf_live_editor.__version__, str)


def test_submodules_import():
    """Validation and model submodules import without side effects."""
    for name in (
        'urdf_live_editor.validation.schema',
        'urdf_live_editor.validation.topology',
        'urdf_live_editor.validation.joint_rules',
        'urdf_live_editor.model.edit_ops',
        'urdf_live_editor.model.version_store',
    ):
        assert importlib.import_module(name) is not None
