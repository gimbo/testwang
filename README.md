# testwang - because randomly-failing tests hurt everyone's brain

`testwang` is a tool that helps out when you've got some randomly
failing python tests, simply by running the tests again in `pytest`,
potentially multiple times, and reporting on the results nicely.

It takes as input a text file containing a list of tests in the dotted
path format found in a Jenkins `testReport`.  It runs those tests
again, and for each test tells you if it consistently PASSED, FAILED,
SKIPPED, etc. or if the results were MIXED (and if so, how mixed).  It
can show you the detail of that if you want, and it can show you the
full `pyest` output if you want - though by default it does neither of
those things.  Aaaand... that's basically it.

## Motivation

If you're ever in the unfortunate position of working on a codebase
which has some randomly failing tests that nobody _quite_ has time to
fix, those tests are noise.  This is annoying.  Let's say you're
working on some feature branch, and you run CI on it, and you get 10
failing tests...  Which are real failures introduced by your branch,
and which are just random noise?

As a first stab, the
[jen-compare](https://github.com/gimbo/gentle-jenkins-tools) tool can
help, e.g. by showing you only the tests which failed on your branch's
CI run but not on `develop`'s last run (say).  So maybe after running
that you end up with 4 tests which failed in your branch but not on
`develop` (at least, not _last time_).

OK, that helps - but it's quite possible some of those failures are
"randos" and can be ignored. The question is: which ones?  To be
certain, you need to run them all again.  In fact, to be _really_
certain, in the face of the crippling anxiety introduced into your
life by all these stupid random failures on this blessed project, you
probably want to run them again _a few times_.  And doing that
yourself is _boring_.  Let `testwang` do the boring thing for you.

## Installation

The simplest way is probably:

    pip install -e git+https://github.com/gimbo/testwang.git#egg=testwang

Alternatively, clone/download this repo and run `setup.py install` if
that's your thing.

Either way you should end up with a `testwang` executable in your
path.

### Requirements

`testwang` (currently) has no third-party package requirements.  That
may well change.

I believe it to be compatible with pythons 2.7 and 3.4+, but I haven't
got round to putting in place structures to verify that yet.

## Usage

### Example

    testwang /tmp/failures.txt -N3 --reuse-db -n4 -e

Here we tell `testwang` to run the tests in `/tmp/failures.txt` three
times (`-N3`), and to echo `pytest`'s output as it runs (`-e`); we
tell `pytest` to reuse an existing DB and to use four parallel test
workers (the `--reuse-db` and `-n 4` args are passed to `pytest`
unchanged).

### Input file

`testwang` takes as input a file containing a list of test paths (as
might be found in a Jenkins `testReport`, say), e.g.:

    apps.thing.tests.test_some_thing.SomeThingTest.test_whatever
    apps.other.tests.test_weird_other_thing.NastyTest.test_weirdness
    tests.integration.test_pathways.test_happy_path

(These can't be used directly with `pytest`, so part of `testwang`'s
job is to convert them into something that can, e.g.:

    apps/thing/tests/test_some_thing.py::SomeThingTest::test_whatever

We may allow this format in the input file in the future too, as that
seems an obvious thing to want to do.)

Blank lines or lines starting with `#` are ignored.

### Arguments/options

Run the script with the `-h`/`--help` for details, but note in
particular:

* The `-P`/`--python` argument specifies which python executable to
  use when running `pytest`; this allows you to e.g. run using a given
  virtualenv's python in order to pick up any needed packages (maybe
  including the system under test).

  However, you may not need to do that: by default, `testwang` just
  uses whatever `python` was used to launch it - so if you `pip`
  install `testwang` straight into your virtualenv and run it from
  there, it should use the right python automatically.

* The `-N`/`--cycles` argument specifies how many cycles to run; the
  default is just once.

* The `-F`/`--failure-focus` argument specifies that as soon as a
  given test passes, it needn't be run again in later cycles; it also
  specifies that only tests that consistently FAILED are reported at
  the end.  As the name suggests, this mode is useful for focussing
  particularly on failing tests.

* The `-R`/`--report-cycles` argument activates reporting of per-cycle
  results at the end, rather that just the overall result for each
  test.

* By default, `pytest`'s output is suppressed. The `-e`/`--echo`
  argument shows it for all cycles, and the `-E`/`--echo-final` shows
  it for only the final cycle.

* Unrecognized arguments are passed through to `pytest` unchanged,
  allowing control over database reuse/creation, parallel execution
  using [`pytest-xdist`](https://github.com/pytest-dev/pytest-xdist),
  etc.

* Your environment is passed through to `pytest` unchanged - so
  `$PYTEST_ADDOPTS` will be picked up, e.g.

## Future work

* Option to stop cycling early if we reach a (thresholded) fixed point.
* Time estimates for all runs except first, based on previous runs.
* Be clever about `--create-db`: only pass to `pytest` on first cycle.
* Allow tests to be specified in pytest format too.
* Colours!
* Some tests would be nice; this started as a small hacky script but
  it's now grown to the point where it really could do with that
  support.
* Prove/document compatability across python versions.
* Maybe more...

## The name

`testwang` is, of course, named after the classic maths quiz
[Numberwang](https://www.google.com/search?q=numberwang).

> That's Numberwang!
