#!/usr/bin/env python

from distutils.core import setup


setup(
    name='testwang',
    version='0.1',
    url='https://github.com/gimbo/testwang',
    author='Andy Gimblett',
    description='A tool for working with randomly-failing tests',
    entry_points={
        'console_scripts': [
            'testwang=testwang:main',
        ],
    },
)
