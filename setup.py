from setuptools import setup, find_packages

version = "0.1.0"

with open("./README.md") as fd:
    long_description = fd.read()

setup(
    name="nuggt",
    version=version,
    description=
    "NeUroproof Ground Truth: cell center annotator using Neuroproof",
    long_description=long_description,
    install_requires=[
        "numpy",
        "neuroglancer",
        "tifffile"
    ],
    author="Kwanghun Chung Lab",
    packages=["nuggt"],
    entry_points={ 'console_scripts': [
        'nuggt=nuggt.main:main'
    ]},
    url="https://github.com/chunglabmit/nuggt",
    license="MIT",
    classifiers=[
        "Development Status :: 3 - Alpha",
        'Programming Language :: Python :: 3.5',
    ]
)