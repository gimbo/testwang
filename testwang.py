#!/usr/bin/env python

"""testwang - a tool for working with randomly-failing tests."""

from __future__ import (
    absolute_import,
    division,
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


class ResultForOneTestRun(object):
    def __init__(self, outcome, duration):
        self.outcome = outcome
        self.duration = duration


class ResultsForOneTest(object):

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


class Observable(object):

    def __init__(self):
        self._observers = []

    def register(self, observer):
        self._observers.append(observer)

    def notify(self, fn_name, *args, **kwargs):
        for observer in self._observers:
            try:
                fn = getattr(observer, fn_name)
            except AttributeError:
                if not getattr(observer, 'strict', True):
                    continue
                else:
                    raise NotImplementedError((observer, fn_name))
            fn(*args, **kwargs)

    def copy_observers_to(self, other):
        for observer in self._observers:
            other.register(observer)


class Testwanger(Observable):

    def __init__(self, collector, runner):
        super(Testwanger, self).__init__()
        self.collector = collector
        self.runner = runner

    def testwang(self):
        start = time.time()
        tests, results, actual_cycles = self.collect_and_run_tests()
        elapsed = time.time() - start
        self.notify(
            'all_cycles_finished',
            tests,
            results,
            actual_cycles,
            elapsed,
        )

    def collect_and_run_tests(self):
        tests = self.collector.collect_tests()
        if not tests:
            self.notify('no_tests_found')
            return
        results, actual_cycles = self.runner.run_tests(tests)
        return tests, results, actual_cycles


class TestCollector(Observable):

    def __init__(self, tests_file_path):
        super(TestCollector, self).__init__()
        self.tests_file_path = tests_file_path

    def collect_tests(self):
        self.notify('collecting_tests', self.tests_file_path)
        tests = self.convert_jenkins_test_specs_to_pytest_format(
            self.get_tests_to_examine(self.tests_file_path),
        )
        self.notify('collected_tests', tests)
        return tests

    @staticmethod
    def get_tests_to_examine(tests_file_path):
        with io.open(tests_file_path, encoding='utf-8') as infile:
            lines = [line.strip() for line in infile.readlines()]
        return [
            line for line in lines
            if line and not line.startswith('#')
        ]

    def convert_jenkins_test_specs_to_pytest_format(self, test_specs):
        return [
            self.convert_jenkins_test_spec_to_pytest_format(test_spec)
            for test_spec in test_specs
        ]

    def convert_jenkins_test_spec_to_pytest_format(self, test_spec):
        test_spec_parts = test_spec.split('.')
        module_path_parts = self.compute_test_spec_module_path_parts(
            test_spec_parts,
        )
        test_path_parts = test_spec_parts[len(module_path_parts):]
        module_path = '/'.join(module_path_parts) + '.py'
        test_path = '::'.join(test_path_parts)
        return module_path + '::' + test_path

    def compute_test_spec_module_path_parts(self, test_spec_parts):
        for prefix in sliced_prefixes(test_spec_parts):
            path = os.path.join(*prefix) + '.py'
            if os.path.exists(path) and os.path.isfile(path):
                return prefix
        self.notify('test_not_found', test_path=test_spec_parts)
        raise TestSpecModuleNotFound(test_spec_parts)


class TestCyclesRunner(Observable):

    def __init__(
        self,
        requested_cycles,
        failure_focus,
        pytest_python,
        pytest_echo,
        pytest_json_path,
        pytest_extra_args,
    ):
        super(TestCyclesRunner, self).__init__()
        self.requested_cycles = requested_cycles
        self.failure_focus = failure_focus
        self.pytest_python = pytest_python
        self.pytest_echo = pytest_echo
        self.pytest_json_path = pytest_json_path
        self.pytest_extra_args = pytest_extra_args

    def run_tests(self, tests):
        results = {
            test: ResultsForOneTest() for test in tests
        }
        active_tests = list(tests)
        actual_cycles = 0
        for cycle in range(self.requested_cycles):
            active_tests = self.run_tests_cycle(cycle, active_tests, results)
            if active_tests:
                actual_cycles += 1
            else:
                break
        return results, actual_cycles

    def run_tests_cycle(self, cycle, active_tests, results):
        if not active_tests:
            self.notify('no_active_tests')
            return []
        estimated_cycle_time = self.estimate_cycle_time(active_tests, results)
        self.notify(
            'test_cycle_began',
            cycle,
            active_tests,
            estimated_cycle_time,
        )
        duration, cycle_results = self.run_tests_for_cycle(active_tests, cycle)
        self.notify('test_cycle_ended', cycle, duration)
        for test in active_tests:
            if test in cycle_results:
                results[test].append(cycle_results[test])
        if self.failure_focus:
            active_tests = [
                test for test in active_tests
                if (
                    test not in cycle_results  # No result: problem?
                    or cycle_results[test].outcome != 'PASSED'
                )
            ]
        return active_tests

    @staticmethod
    def estimate_cycle_time(tests, prior_results):
        return sum(prior_results[test].mean_duration for test in tests)

    def run_tests_for_cycle(self, tests, cycle):
        command = self.construct_tests_run_command(tests)
        self.notify('pytest_command', command)
        final_cycle = cycle == self.requested_cycles - 1
        echoing = (
            self.pytest_echo == 'ALL'
            or (self.pytest_echo == 'FINAL' and final_cycle)
        )
        duration, _ = run_timed(self.run_command, command, echo=echoing)
        results = self.parse_json_results()
        return duration, results

    def construct_tests_run_command(self, tests):
        command = [os.path.expanduser(self.pytest_python), '-m', 'pytest']
        command.extend(self.pytest_extra_args)
        command.append('--json={}'.format(self.pytest_json_path))
        command.extend(tests)
        return command

    @staticmethod
    def run_command(command, echo):
        stdout = stderr = None if echo else subprocess.PIPE
        process = subprocess.Popen(
            command,
            stdout=stdout,
            stderr=stderr,
            env=copy.deepcopy(os.environ),
        )
        process.communicate()
        return process.returncode

    def parse_json_results(self):
        with io.open(self.pytest_json_path, encoding='utf-8') as json_file:
            contents = json.load(json_file)
        return dict((
            self.parse_json_results_one_test(test_json)
            for test_json in contents['report']['tests']
        ))

    @staticmethod
    def parse_json_results_one_test(test_json):
        name = test_json['name']
        outcome = test_json['outcome'].upper()
        duration = sum((
            section.get('duration', 0)
            for section in test_json.values()
            if isinstance(section, dict)
        ))
        return name, ResultForOneTestRun(outcome, duration)


# noinspection PyMethodMayBeStatic
class TestwangConsoleOutput(object):

    strict = True

    def __init__(
        self,
        requested_cycles,
        failure_focus,
        report_cycle_detail,
        debug=False
    ):
        self.requested_cycles = requested_cycles
        self.failure_focus = failure_focus
        self.report_cycle_detail = report_cycle_detail
        self._debug = debug

    def debug(self, *args, **kwargs):
        if self._debug:
            print(*args, **kwargs)

    def test_not_found(self, test_path):
        print('Test not found: {}'.format(test_path))

    def no_tests_found(self):
        print('No tests found')

    def collecting_tests(self, tests_file_path):
        print('Collecting tests from {}'.format(unexpand_user(tests_file_path)))

    def collected_tests(self, tests):
        print('\nWill run the following {} tests:\n'.format(len(tests)))
        for test in tests:
            print('  ' + test)
        print('')

    def no_active_tests(self):
        print('No tests to run')

    def test_cycle_began(self, cycle, tests, estimated_cycle_time):
        if estimated_cycle_time:
            estimate = ', time estimate: {:5.2f}s'.format(estimated_cycle_time)
        else:
            estimate = ''
        header = self._header_for_test_cycle(cycle)
        print('{}{} tests to run{}'.format(header, len(tests), estimate))

    def _header_for_test_cycle(self, cycle):
        return 'Test cycle {:2} of {:2}  --  '.format(
            cycle + 1,
            self.requested_cycles,
        )

    def pytest_command(self, command):
        self.debug(' '.join(command))

    def test_cycle_ended(self, cycle, duration):
        indent = ' ' * len(self._header_for_test_cycle(cycle))
        print(indent + '{:.2f}s for cycle'.format(duration))

    def all_cycles_finished(self, tests, results, actual_cycles, elapsed):

        longest_outcome = max((
            len(outcome) for outcome in self._all_test_result_outcomes(results)
        ))
        template = '{{:{}}} {{}}s'.format(longest_outcome)

        print('\nRan {} {} of tests in {:5.2f}s\n'.format(
            actual_cycles,
            'cycle' if self.requested_cycles == 1 else 'cycles',
            elapsed,
        ))
        for test in tests:
            test_results = results[test]
            if self.failure_focus and test_results.overall_outcome != 'FAILED':
                continue
            print(template.format(test_results.overall_outcome, test))
            if self.report_cycle_detail:
                self.report_test_cycle_result(
                    test_results,
                    longest_outcome,
                )

    def _all_test_result_outcomes(self, results):
        outcomes = set()
        for test_result in results.values():
            outcomes.add(test_result.overall_outcome)
            for cycle_result in test_result:
                outcomes.add(cycle_result.outcome)
        return outcomes

    def report_test_cycle_result(self, test_results, longest_outcome):

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


def main():
    args, pytest_extra_args = parse_args()
    collector = TestCollector(args.tests_file_path)
    runner = TestCyclesRunner(
        requested_cycles=args.requested_cycles,
        failure_focus=args.failure_focus,
        pytest_python=args.pytest_python,
        pytest_echo=args.pytest_echo,
        pytest_json_path=args.pytest_json_path,
        pytest_extra_args=pytest_extra_args,
    )
    wanger = Testwanger(
        collector=collector,
        runner=runner,
    )
    console_output = TestwangConsoleOutput(
        requested_cycles=args.requested_cycles,
        failure_focus=args.failure_focus,
        report_cycle_detail=args.report_cycles,
        debug=args.debug,
    )
    for observable in (collector, runner, wanger):
        observable.register(console_output)
    try:
        wanger.testwang()
    except TestSpecModuleNotFound:
        sys.exit(1)


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
        dest='pytest_json_path',
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
        dest='requested_cycles',
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
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Activate debug output',
    )

    # We will pass any unrecognized args through to pytest
    args, pytest_extra_args = parser.parse_known_args()
    # In case any of those unrecognized args are env vars, expand them.
    pytest_extra_args = tuple(flatten(
        os.path.expandvars(arg).split() for arg in pytest_extra_args
    ))

    if not args.pytest_json_path:
        args.pytest_json_path = create_tmp_json_path_and_register_for_cleanup()

    if args.echo:
        args.pytest_echo = 'ALL'
    elif args.echo_final:
        args.pytest_echo = 'FINAL'
    else:
        args.pytest_echo = None
    del args.echo
    del args.echo_final

    return args, pytest_extra_args


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


def sliced_prefixes(slicable):
    return (slicable[:i] for i in range(1, len(slicable) + 1))


def flatten(iterator):
    return itertools.chain(*iterator)


def run_timed(fn, *args, **kwargs):
    started = time.time()
    result = fn(*args, **kwargs)
    duration = time.time() - started
    return duration, result


if __name__ == '__main__':
    main()
