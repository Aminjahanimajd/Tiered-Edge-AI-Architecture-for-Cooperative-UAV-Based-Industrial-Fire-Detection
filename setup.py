from setuptools import find_packages, setup


setup(
    name="drone-enhanced-core",
    version="0.1.0",
    author="Mohammadamin Jahanimajd",
    license="AGPL-3.0-only",
    url="https://github.com/Aminjahanimajd/Tiered-Edge-AI-Architecture-for-Cooperative-UAV-Based-Industrial-Fire-Detection",
    description="ROS-independent coordination and inference logic for the thesis prototype",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.6",
)
