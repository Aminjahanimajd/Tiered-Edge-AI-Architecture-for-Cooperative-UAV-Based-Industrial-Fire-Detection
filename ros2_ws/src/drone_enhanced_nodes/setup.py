from setuptools import setup


PACKAGE_NAME = "drone_enhanced_nodes"


setup(
    name=PACKAGE_NAME,
    version="0.1.0",
    packages=[PACKAGE_NAME],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + PACKAGE_NAME]),
        ("share/" + PACKAGE_NAME, ["package.xml"]),
        ("share/" + PACKAGE_NAME + "/config", ["config/runtime.yaml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=False,
    maintainer="Mohammadamin Jahanimajd",
    maintainer_email="Aminjahanimajd@users.noreply.github.com",
    description="Correlated Sentinel and Scout fire-detection research nodes.",
    license="AGPL-3.0-only",
    entry_points={
        "console_scripts": [
            "sentinel_node = drone_enhanced_nodes.sentinel_node:main",
            "scout_node = drone_enhanced_nodes.scout_node:main",
        ],
    },
)
