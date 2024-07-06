from setuptools import setup
from setuptools.extension import Extension
from Cython.Build import cythonize

extensions = [
    Extension("optimized_functions", ["optimized_functions.pyx"], libraries=["aiohttp"])
]

setup(
    name="optimized_functions",
    ext_modules=cythonize(extensions),
)
