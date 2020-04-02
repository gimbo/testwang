import pytest

from testwang import Collector


@pytest.mark.parametrize(
    'test_spec, expected',
    (
        ('bar.py', ((), 'bar', ())),
        ('foo/bar.PY', (('foo',), 'bar', ())),
        ('bar.py::xx', ((), 'bar', ('xx',))),
        ('foo/bar.py::xx', (('foo',), 'bar', ('xx',))),
        ('foo/bar.py::xx::yy', (('foo',), 'bar', ('xx', 'yy'))),
        ('foo/moo/bar.py::xx::yy', (('foo', 'moo'), 'bar', ('xx', 'yy'))),
    )
)
def test_pytest_test_spec(test_spec, expected):
    parsed = Collector.parse_pytest_test_spec(test_spec)
    assert parsed == expected


@pytest.mark.parametrize(
    'test_spec',
    (
        '',
        'foo',
        'foo/bar::xx:yy',
        'foo/bar.py/xx:yy'
        'foo/bar.py/xx::yy'
        'foo/bar.py/xx/yy'
        'foo/bar.py.xx.yy'
        'foo.bar.xx.yy',
    )
)
def test_pytest_test_spec_failures(test_spec):
    with pytest.raises(ValueError):
        Collector.parse_pytest_test_spec(test_spec)
