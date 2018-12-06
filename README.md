# testwang - because randomly-failing tests hurt everyone's brain

This is a tool to help out when you've got some randomly failing
python tests.  It helps by running the tests again in pytest, to let
you pin down which ones really are randomly failing, and which are
not.

## Motivation

While working on a project with a number of randomly failing tests in
the `develop` branch, those tests show up as noise when running CI on
any feature branch.  Using
[compare_jenkins](https://github.com/gimbo/compare_jenkins) helps, by
filtering out tests which failed in both branches (that also helps by
eliminating tests which are _always_ failing in `develop` of course) -
but then you can still end up with some tests that (randomly) failed
in the feature branch but not `develop`.

So you need to run just those tests vs the feature branch and see if
they pass (at least some of the time). Doing that yourself is
_boring_.  Let `testwang` do the boring thing for you.

## Usage

`testwang` takes as input a file containing a list of test paths (as
might be found in a Jenkins `testReport`, say), e.g.:

    apps.thing.tests.test_some_thing.SomeThingTest.test_whatever
    apps.other.tests.test_weird_other_thing.NastyTest.test_weirdness
    tests.integration.test_pathways.test_happy_path

and (at time of writing) it simply runs all those tests again, once,
via pytest. The next stage will be to run them multiple times,
collecting info on how many times each fails and reporting on that.
There may be more advanced possibilities to come after that, we'll
see...

Run the script with the `-h`/`--help` for details, but note in
particular:

* The `-P`/`--python` argument lets you specify which python
  executable to use to run `pytest`; this allows you to e.g. run using
  a given virtualenv's version python in order to pick up any needed
  packages (e.g., perhaps, the system under test).

  However, you may not need to do that: by default, `testwang` just
  uses whatever `python` was used to launch it - so if you `pip`
  install `testwang` straight into your virtualenv and run it from
  there, it should use the right python automatically.

* By default, `pytest`'s output is suppressed. Use the `-e`/`--echo`
  argument to see it.

* Unrecognized arguments are passed through to `pytest` unchanged,
  allowing control over database reuse/creation, parallel execution
  using [`pytest-xdist`](https://github.com/pytest-dev/pytest-xdist),
  etc.

* Your environment is passed through to `pytest` unchanged - so
  `$PYTEST_ADDOPTS` will be picked up, e.g.

### Example

    $ testwang /tmp/failures.txt --reuse-db -n 4 -e

Here `-e` tells `testwang` to echo `pytest`'s output, and the other
options are passed through to `ptest` unchanged.

## The name

`testwang` is, of course, named after the classic maths quiz
[Numberwang](https://www.google.com/search?q=numberwang).

> That's Numberwang!
