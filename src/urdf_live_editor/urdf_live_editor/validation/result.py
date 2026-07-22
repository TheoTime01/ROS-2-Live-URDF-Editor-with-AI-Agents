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
Result types shared by every deterministic validation check.

A :class:`ValidationResult` is an ordered collection of
:class:`ValidationIssue` records. The engine composes the schema, topology,
and joint-rule checks by merging their results; a candidate model is
considered valid only when no issue has ``ERROR`` severity.
"""

from dataclasses import dataclass, field
import enum
from typing import List, Optional


class Severity(enum.Enum):
    """Severity of a single validation issue."""

    ERROR = 'error'
    WARNING = 'warning'

    def __str__(self):
        """Return the lowercase severity label."""
        return self.value


@dataclass(frozen=True)
class ValidationIssue:
    """A single diagnostic produced by a validation check."""

    code: str
    message: str
    severity: Severity = Severity.ERROR
    subject: Optional[str] = None

    def __str__(self):
        """Return a compact ``severity[code] subject: message`` string."""
        subject = ' %s:' % self.subject if self.subject else ''
        return '%s[%s]%s %s' % (
            self.severity, self.code, subject, self.message)

    def to_dict(self):
        """Return a JSON-serializable view of this issue."""
        return {
            'code': self.code,
            'message': self.message,
            'severity': self.severity.value,
            'subject': self.subject,
        }


@dataclass
class ValidationResult:
    """An ordered set of issues plus convenience accessors."""

    issues: List[ValidationIssue] = field(default_factory=list)

    @classmethod
    def ok(cls):
        """Return an empty (valid) result."""
        return cls([])

    def add(self, code, message, severity=Severity.ERROR, subject=None):
        """Append a new issue and return this result for chaining."""
        self.issues.append(
            ValidationIssue(code, message, severity, subject))
        return self

    def add_error(self, code, message, subject=None):
        """Append an ``ERROR``-severity issue and return this result."""
        return self.add(code, message, Severity.ERROR, subject)

    def add_warning(self, code, message, subject=None):
        """Append a ``WARNING``-severity issue and return this result."""
        return self.add(code, message, Severity.WARNING, subject)

    def extend(self, other):
        """Merge the issues of ``other`` into this result and return it."""
        self.issues.extend(other.issues)
        return self

    @property
    def errors(self):
        """Return the list of ``ERROR``-severity issues."""
        return [i for i in self.issues if i.severity is Severity.ERROR]

    @property
    def warnings(self):
        """Return the list of ``WARNING``-severity issues."""
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def is_valid(self):
        """Return ``True`` when the result carries no error-severity issue."""
        return not self.errors

    @property
    def codes(self):
        """Return the ordered list of issue codes."""
        return [i.code for i in self.issues]

    def has_code(self, code):
        """Return ``True`` when some issue carries ``code``."""
        return any(i.code == code for i in self.issues)

    def __bool__(self):
        """Return the validity of the result (truthy when valid)."""
        return self.is_valid

    def __iter__(self):
        """Iterate over the contained issues."""
        return iter(self.issues)

    def __len__(self):
        """Return the number of issues."""
        return len(self.issues)

    def to_dict(self):
        """Return a JSON-serializable view of the whole result."""
        return {
            'is_valid': self.is_valid,
            'issues': [i.to_dict() for i in self.issues],
        }
