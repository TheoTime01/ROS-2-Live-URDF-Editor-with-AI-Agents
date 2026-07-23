from setuptools import find_packages, setup

package_name = "urdf_live_editor"

setup(
    name=package_name,
    version="0.6.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/config", ["config/validation_policy.yaml"]),
    ],
    install_requires=["setuptools", "PyYAML"],
    zip_safe=True,
    maintainer="Project maintainers",
    maintainer_email="titanblack733@gmail.com",
    description="Deterministic core + observability + launch/config integration "
    "+ Milestone 6 extensions (ros2_control, Gazebo, multi-model sessions, "
    "physical validation) for the ROS 2 Live URDF Editor.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # ROS node entry points are added in Milestones 1-3, e.g.:
            # "urdf_source_node = urdf_live_editor.urdf_source_node:main",
        ],
    },
)
