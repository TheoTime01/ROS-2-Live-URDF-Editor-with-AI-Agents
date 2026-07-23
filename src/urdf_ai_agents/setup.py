from setuptools import find_packages, setup

package_name = "urdf_ai_agents"

setup(
    name=package_name,
    version="0.5.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Project maintainers",
    maintainer_email="titanblack733@gmail.com",
    description="Claude Agent SDK layer for the ROS 2 Live URDF Editor "
    "(Milestone 5: Launch/Integration Agent).",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            # "ai_agent_node = urdf_ai_agents.ai_agent_node:main",  # Milestone 4
        ],
    },
)
