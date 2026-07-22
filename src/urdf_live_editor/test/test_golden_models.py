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

"""Golden-model tests: known-good/known-broken URDFs to expected verdicts."""

import glob
import os

import pytest

from urdf_live_editor.validation.engine import validate_urdf_string

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODELS = os.path.join(_HERE, 'models')

# Each broken model must be invalid and must raise at least this code.
BROKEN_EXPECTED = {
    'duplicate_link.urdf': 'SCHEMA_DUPLICATE_LINK',
    'missing_child_link.urdf': 'SCHEMA_JOINT_UNKNOWN_CHILD',
    'two_roots.urdf': 'TOPO_MULTIPLE_ROOTS',
    'cycle.urdf': 'TOPO_NO_ROOT',
    'multiple_parents.urdf': 'TOPO_MULTIPLE_PARENTS',
    'revolute_no_limit.urdf': 'JOINT_MISSING_LIMIT',
    'zero_axis.urdf': 'JOINT_ZERO_AXIS',
    'inverted_limit.urdf': 'JOINT_LIMIT_INVERTED',
    'malformed.urdf': 'SCHEMA_MALFORMED_XML',
}


def _read(path):
    """Return the text contents of ``path``."""
    with open(path, 'r') as handle:
        return handle.read()


def _good_models():
    """Return the paths of every known-good golden model."""
    return sorted(glob.glob(os.path.join(_MODELS, 'good', '*.urdf')))


@pytest.mark.parametrize('path', _good_models())
def test_good_models_validate(path):
    """Every known-good golden model passes validation."""
    _model, result = validate_urdf_string(_read(path))
    assert result.is_valid, '%s: %s' % (
        os.path.basename(path), result.codes)


@pytest.mark.parametrize('filename,code', sorted(BROKEN_EXPECTED.items()))
def test_broken_models_are_rejected(filename, code):
    """Every known-broken golden model is invalid with its expected code."""
    path = os.path.join(_MODELS, 'broken', filename)
    _model, result = validate_urdf_string(_read(path))
    assert not result.is_valid
    assert result.has_code(code), '%s: got %s' % (filename, result.codes)


def test_broken_directory_is_covered():
    """Every file in the broken/ directory has an expectation entry."""
    on_disk = {
        os.path.basename(p)
        for p in glob.glob(os.path.join(_MODELS, 'broken', '*.urdf'))}
    assert on_disk == set(BROKEN_EXPECTED)
