#!/usr/bin/env python

"""testwang - a tool for working with randomly-failing tests."""

from __future__ import (
    print_function,
    unicode_literals,
)

import argparse
import copy
import itertools
import os
import subprocess
import sys


class TestSpecModuleNotFound(Exception):
    @property
    def path(self):
        return '.'.join(self.args[0])


def main():
    args, pytest_args = parse_args()
    # print(args)
    # print(pytest_args)
    try:
        collect_and_run_tests(args, pytest_args)
    except TestSpecModuleNotFound as ex:
        print('Test not found: {}'.format(ex.path))
        sys.exit(1)


def collect_and_run_tests(args, pytest_args):
    tests = collect_tests(args)
    if not tests:
        print('No tests found.')
        return
    report_tests_to_run(tests, args.echo)
    run_tests(tests, args, pytest_args)


def collect_tests(args):
    print('Collecting tests from {}'.format(
        unexpand_user(args.tests_file_path))
    )
    return convert_jenkins_test_specs_to_pytest_format(
        get_tests_to_examine(args.tests_file_path),
    )


def get_tests_to_examine(tests_file_path):
    with open(tests_file_path) as infile:
        lines = [line.strip() for line in infile.readlines()]
    return [
        line for line in lines
        if line and not line.startswith('#')
    ]


def convert_jenkins_test_specs_to_pytest_format(test_specs):
    return [
        convert_jenkins_test_spec_to_pytest_format(test_spec)
        for test_spec in test_specs
    ]


def convert_jenkins_test_spec_to_pytest_format(test_spec):
    test_spec_parts = test_spec.split('.')
    module_path_parts = compute_test_spec_module_path_parts(test_spec_parts)
    test_path_parts = test_spec_parts[len(module_path_parts):]
    module_path = '/'.join(module_path_parts) + '.py'
    test_path = '::'.join(test_path_parts)
    return module_path + '::' + test_path


def compute_test_spec_module_path_parts(test_spec_parts):
    for prefix in sliced_prefixes(test_spec_parts):
        path = os.path.join(*prefix) + '.py'
        if os.path.exists(path) and os.path.isfile(path):
            return prefix
    raise TestSpecModuleNotFound(test_spec_parts)


def sliced_prefixes(slicable):
    return (slicable[:i] for i in range(1, len(slicable) + 1))


def report_tests_to_run(tests, echo):
    print('Will run the following {} tests:'.format(len(tests)))
    for test in tests:
        print('  ' + test)
    if echo:
        print()
    else:
        print('Use the --echo option if you want to see output as they run.')


def run_tests(tests, args, pytest_args):
    command = construct_tests_run_command(
        tests,
        os.path.expanduser(args.pytest_python),
        pytest_args,
    )
    returncode = run_command(command, args.echo)
    print('Return code: {}'.format(returncode))


def construct_tests_run_command(tests, pytest_python, pytest_args):
    command = [pytest_python, '-m', 'pytest']
    command.extend(pytest_args)
    command.extend(tests)
    return command


def run_command(args, echo):
    stdout = stderr = None if echo else subprocess.PIPE
    env = copy.deepcopy(os.environ)
    process = subprocess.Popen(args, stdout=stdout, stderr=stderr, env=env)
    process.communicate()
    return process.returncode


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'tests_file_path', metavar='TESTS_FILE_PATH',
        help='Path to file containing failing tests spec',
    )
    parser.add_argument(
        '-P', '--python', metavar='PYTHON', dest='pytest_python',
        nargs='?',
        default=sys.executable,
        help=(
            'Path to python executable to use to run pytest; default is '
            'whichever python is being used to run this script, currently: {}'
        ).format(unexpand_user(sys.executable))
    )
    parser.add_argument(
        '-e', '--echo',
        action='store_true',
        help='Echo pytest output as it runs; default is to suppress it',
    )
    args, pytest_args = parser.parse_known_args()
    pytest_args = tuple(itertools.chain(*(
        os.path.expandvars(arg).split() for arg in pytest_args
    )))
    return args, pytest_args


def unexpand_user(path):
    return path.replace(os.path.expanduser('~'), '~')


if __name__ == '__main__':
    main()
