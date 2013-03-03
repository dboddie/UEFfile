#! /usr/bin/env python

from distutils.core import setup

from UEFfile import version

setup(
    name         = "UEFfile",
    description  = "UEF file handling support for Python.",
    author       = "David Boddie",
    author_email = "david@boddie.org.uk",
    url          = "http://www.boddie.org.uk/david/Projects/",
    version      = version,
    py_modules      = ["UEFfile"]
    )
