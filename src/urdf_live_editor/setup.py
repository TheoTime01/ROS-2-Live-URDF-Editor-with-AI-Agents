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

"""Package configuration for the deterministic ``urdf_live_editor`` core."""

from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'urdf_live_editor'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml')),
        (os.path.join('share', package_name, 'rviz'),
            glob('rviz/*.rviz')),
        # The canonical sample robot lives at the repository root; install a
        # copy into the package share so launch files and launch tests can find
        # it via get_package_share_directory (works from an installed tree).
        (os.path.join('share', package_name, 'models', 'sample_arm'),
            glob('../../models/sample_arm/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='theotime01',
    maintainer_email='titanblack733@gmail.com',
    description='Deterministic core for live URDF editing and validation.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'urdf_source_node = '
            'urdf_live_editor.urdf_source_node:main',
            'constraint_validation_node = '
            'urdf_live_editor.constraint_validation_node:main',
            'joint_state_adapter_node = '
            'urdf_live_editor.joint_state_adapter_node:main',
            'model_update_coordinator_node = '
            'urdf_live_editor.model_update_coordinator_node:main',
            'web_api_node = '
            'urdf_live_editor.web_api_node:main',
        ],
    },
)
