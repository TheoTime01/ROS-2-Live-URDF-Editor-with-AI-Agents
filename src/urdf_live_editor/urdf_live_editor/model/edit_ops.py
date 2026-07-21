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

"""``EditOperation`` types and their ``apply`` semantics.

Defines the unit of change (``add_link``, ``add_joint``, ``update_joint``,
``remove_joint``, ``set_joint_limit``, ``set_joint_axis``, ``rename``) and
how each is applied to a staged candidate model. Implemented in Milestone 1.
"""
