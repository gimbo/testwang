#!/usr/bin/env python

"""testwang - a tool for working with randomly-failing tests."""

from __future__ import (
    print_function,
    unicode_literals,
)

import argparse
import atexit
import copy
import io
import itertools
import json
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter


class TestSpecModuleNotFound(Exception):
    @property
    def path(self):
        return '.'.join(self.args[0])


class ResultForOneTestRun:
    def __init__(self, outcome, duration):
        self.outcome = outcome
        self.duration = duration


class ResultsForOneTest:

    def __init__(self):
        self.cycle_results = []

    def __iter__(self):
        return iter(self.cycle_results)

    def __len__(self):
        return len(self.cycle_results)

    @property
    def overall_outcome(self):
        try:
            first_outcome = self.cycle_results[0].outcome
        except IndexError:
            return 'NOT RUN'
        all_outcomes = set((result.outcome for result in self))
        if {first_outcome} == all_outcomes:
            return first_outcome
        else:
            return 'MIXED ({:.0f}%)'.format(100 * self.outcome_consistency)

    @property
    def outcome_consistency(self):
        outcome_counts = Counter((result.outcome for result in self))
        if not outcome_counts:
            return 0
        top_freq = list(sorted(outcome_counts.values()))[-1]
        total_freq = sum(outcome_counts.values())
        return float(top_freq) / total_freq

    @property
    def total_duration(self):
        return sum((result.duration for result in self))

    @property
    def mean_duration(self):
        cycles = len(self)
        return self.total_duration / cycles if cycles else 0

    def append(self, result_for_one_test_run):
        self.cycle_results.append(result_for_one_test_run)


def main():
    args, pytest_args = parse_args()
    testwang(args, pytest_args)


def testwang(args, pytest_args):
    start = time.time()
    try:
        tests, results, actual_cycles = collect_and_run_tests(
            args,
            pytest_args,
        )
    except TestSpecModuleNotFound as ex:
        print('Test not found: {}'.format(ex.path))
        sys.exit(1)
    elapsed = time.time() - start
    report_overall_results(args, tests, results, actual_cycles, elapsed)


def collect_and_run_tests(args, pytest_args):
    tests = collect_tests(args)
    if not tests:
        print('No tests found.')
        return
    report_tests_to_run(tests)
    results, actual_cycles = run_tests(tests, args, pytest_args)
    return tests, results, actual_cycles


def collect_tests(args):
    print('Collecting tests from {}'.format(
        unexpand_user(args.tests_file_path))
    )
    return convert_jenkins_test_specs_to_pytest_format(
        get_tests_to_examine(args.tests_file_path),
    )


def get_tests_to_examine(tests_file_path):
    with io.open(tests_file_path, encoding='utf-8') as infile:
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


def report_tests_to_run(tests):
    print('\nWill run the following {} tests:\n'.format(len(tests)))
    for test in tests:
        print('  ' + test)
    print('')


def run_tests(tests, args, pytest_args):
    results = {
        test: ResultsForOneTest() for test in tests
    }
    active_tests = list(tests)
    actual_cycles = 0
    for cycle in range(args.cycles):
        if not active_tests:
            print('No tests to run')
            break
        cycle_results = run_and_report_tests_cycle(
            active_tests,
            results,
            args,
            pytest_args,
            cycle,
        )
        actual_cycles += 1
        for test in active_tests:
            if test in cycle_results:
                results[test].append(cycle_results[test])
        if args.failure_focus:
            active_tests = [
                test for test in active_tests
                if (
                    test not in cycle_results  # No result: problem?
                    or cycle_results[test].outcome != 'PASSED'
                )
            ]
    return results, actual_cycles


def run_and_report_tests_cycle(tests, results, args, pytest_args, cycle):
    if args.cycles > 1:
        indent = report_start_of_test_run(
            tests,
            results,
            args.cycles,
            cycle,
        )
    else:
        indent = ''
    duration, results = run_tests_cycle(
        tests,
        results,
        args,
        pytest_args,
        cycle,
    )
    print(indent + '{:.2f}s for cycle'.format(duration))
    return results


def run_tests_cycle(tests, results, args, pytest_args, cycle):
    command = construct_tests_run_command(tests, args, pytest_args)
    final_cycle = cycle == args.cycles - 1
    echoing = args.echo or (args.echo_final and final_cycle)
    duration, _ = run_timed(run_command, command, echo=echoing)
    results = parse_json_results(args.json_path)
    return duration, results


def report_start_of_test_run(tests, results, cycles, cycle):
    time_estimate = estimate_cycle_time(tests, results)
    if cycle > 0:
        estimate = ', time estimate: {:5.2f}s'.format(time_estimate)
    else:
        estimate = ''
    header = 'Test cycle {:2} of {:2}  --  '.format(cycle + 1, cycles)
    print('{}{} tests to run{}'.format(header, len(tests), estimate))
    return ' ' * len(header)


def estimate_cycle_time(tests, prior_results):
    return sum(prior_results[test].mean_duration for test in tests)


def construct_tests_run_command(tests, args, pytest_args):
    command = [os.path.expanduser(args.pytest_python), '-m', 'pytest']
    command.extend(pytest_args)
    command.append('--json={}'.format(args.json_path))
    command.extend(tests)
    return command


def run_command(args, echo):
    stdout = stderr = None if echo else subprocess.PIPE
    env = copy.deepcopy(os.environ)
    process = subprocess.Popen(args, stdout=stdout, stderr=stderr, env=env)
    process.communicate()
    return process.returncode


def parse_json_results(json_path):
    with io.open(json_path, encoding='utf-8') as json_file:
        contents = json.load(json_file)
    return dict((
        parse_json_results_one_test(test_json)
        for test_json in contents['report']['tests']
    ))


def parse_json_results_one_test(test_json):
    name = test_json['name']
    outcome = test_json['outcome'].upper()
    duration = sum((
        section.get('duration', 0)
        for section in test_json.values()
        if isinstance(section, dict)
    ))
    return name, ResultForOneTestRun(outcome, duration)


def report_overall_results(args, tests, results, actual_cycles, elapsed):

    longest_outcome = max((
        len(outcome) for outcome in all_test_result_outcomes(results)
    ))
    template = '{{:{}}} {{}}s'.format(longest_outcome)

    print('\nRan {} {} of tests in {:5.2f}s\n'.format(
        actual_cycles,
        'cycle' if args.cycles == 1 else 'cycles',
        elapsed,
    ))
    for test in tests:
        test_results = results[test]
        if args.failure_focus and test_results.overall_outcome != 'FAILED':
            continue
        print(template.format(test_results.overall_outcome, test))
        if args.report_cycles:
            report_test_cycle_result(
                test_results,
                longest_outcome,
            )


def all_test_result_outcomes(results):
    outcomes = set()
    for test_result in results.values():
        outcomes.add(test_result.overall_outcome)
        for cycle_result in test_result:
            outcomes.add(cycle_result.outcome)
    return outcomes


def report_test_cycle_result(test_results, longest_outcome):

    def indented(msg):
        return ' ' * longest_outcome + ' ' + msg

    inner_template = '{{:{}}} {{:5.2f}}s'.format(longest_outcome)
    for cycle in test_results:
        print(indented(
            inner_template.format(cycle.outcome, cycle.duration),
        ))
    if len(test_results) > 1:
        print(indented(indented('{:5.2f}s total, {:5.2f}s mean\n'.format(
            test_results.total_duration,
            test_results.mean_duration,
        ))))


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
        '-P', '--python', metavar='PYTHON_EXE_PATH', dest='pytest_python',
        default=sys.executable,
        help="""
            Path to python executable to use to run pytest; default is
            whichever python is being used to run this script, currently: {}
        """.format(unexpand_user(sys.executable)),
    )
    parser.add_argument(
        '-J', '--json-path', metavar='JSON_PATH',
        help="""
            File path to store test run results in; by default they are
            stored in a temporary folder and deleted after use. If this
            argument is passed, the temp file is not deleted after use.
            If running multiple test cycles, this will end up containing
            the result of the final test run
        """,
    )
    parser.add_argument(
        '-N', '--cycles',
        default=1,
        type=positive_int,
        help='How many times to run the tests; default is just once',
    )
    parser.add_argument(
        '-F', '--failure-focus',
        action='store_true',
        help="""
            As soon as a test passes once, don't run it again in later cycles.
        """,
    )
    parser.add_argument(
        '-R', '--report-cycles',
        action='store_true',
        help="""
            When reporting test results at end, also report each
            test's result for each cycle, and the time spent in that
            test across all cycles.
        """,
    )

    echo_parser = parser.add_mutually_exclusive_group()
    echo_parser.add_argument(
        '-e', '--echo',
        action='store_true',
        help='Echo pytest output as it runs; default is to suppress it',
    )
    echo_parser.add_argument(
        '-E', '--echo-final',
        action='store_true',
        help="""
            When running multiple cycles, echo pytest output only of final
            test run and suppress output from earlier runs; if running a
            single cycle, this is equivalent to --echo
        """,
    )

    # We will pass any unrecognized args through to pytest
    args, pytest_args = parser.parse_known_args()
    # In case any of those unrecognized args are env vars, expand them.
    pytest_args = tuple(itertools.chain(*(
        os.path.expandvars(arg).split() for arg in pytest_args
    )))

    if not args.json_path:
        args.json_path = create_tmp_json_path_and_register_for_cleanup()

    return args, pytest_args


def create_tmp_json_path_and_register_for_cleanup():
    h, json_path = tempfile.mkstemp()
    os.close(h)
    atexit.register(os.unlink, json_path)
    return json_path


def positive_int(x):
    """Argument value parser: positive integers."""
    try:
        n = int(x)
        if n <= 0:
            raise ValueError()
        return n
    except ValueError:
        raise argparse.ArgumentTypeError(
            'invalid positive int value: {}'.format(x),
        )


def unexpand_user(path):
    return path.replace(os.path.expanduser('~'), '~')


def run_timed(fn, *args, **kwargs):
    started = time.time()
    result = fn(*args, **kwargs)
    duration = time.time() - started
    return duration, result


if __name__ == '__main__':
    main()
