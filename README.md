# CSCS Internship: Automating Spack Package Generation for Python Packages
Github repository for the CSCS internship project with the goal of developing a Python tool for automatically generating Spark package recipes based on existing Python packages, with the ability to handle direct and transitive dependencies and flexible versions.

## Important links
- [Detailed Project Description](<CSCS Internship Project Description.md>)
- [Progress Report](<Progress Report.md>)

## Example Python Package
We created a simple python package called `example-python-package-intern-pyspack` located in `example-python-package/`, using `flit` as the build backend.  
It contains a single module `utils` with two functions `parse_requirements` and `display_packages` for (very basic) parsing of a `requirements.txt` file (e.g. generated by `pip freeze > requirements.txt`) and displaying the package dependencies.

### Installation
The package is hosted on [PyPI](://pypi.org/project/example-python-package-intern-pyspack/) and can be installed using pip:
```bash
python -m pip install example-python-package-intern-pyspack
```
### Usage
```python
"""
Example contents of requirements.txt:
-------------------------------------

package1==1.0.0
package2==1.2.3
bad_package_dependency0.0.1
"""

from example_python_package_intern_pyspack.utils import parse_requirements, display_packages
# or
from example_python_package_intern_pyspack import *

path = "path/to/requirements.txt"

packages = parse_requirements(path)
display_packages(packages)


"""
Example Output:
---------------

package1 : 1.0.0
package2 : 1.2.3

Parse Errors:
bad_package_dependency0.0.1
"""
```



## Example Spack Package
We also created a Spack package based on the PyPI package from before, located in `example-spack-package/`.

### Installation
Assuming that Spack is installed and `$SPACK_ROOT` is set:
```bash
cd intern-pyspack/example-spack-project/
cp -r py-example-python-package-intern-pyspack $SPACK_ROOT/var/spack/repos/builtin/packages/

spack install py-example-python-package-intern-pyspack
spack load py-example-python-package-intern-pyspack

python
>>> import example_python_package_intern_pyspack
```