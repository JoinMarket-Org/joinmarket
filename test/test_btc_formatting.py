#! /usr/bin/env python
from __future__ import absolute_import
'''Test bitcoin module data handling (legacy version)'''

import bitcoin as btc
import pytest

def test_bad_code_string():
    for i in [1,9,257,-3,"256"]:
        with pytest.raises(ValueError) as e_info:
            btc.get_code_string(i)

@pytest.mark.parametrize(
    "st, frm, to, minlen, res",
    [
        ("0101aa", 16, 16, 12, "0000000101aa"),
    ])
def test_changebase(st, frm, to, minlen, res):
    assert btc.changebase(st, frm, to, minlen) == res

#legacy btc elliptic curve code tests
def test_point_at_infinity():
    assert btc.isinf((0,0))
    assert not btc.isinf((0,1))
    assert not btc.isinf((1,0))

#def test_jordan_add():
#    pinf = ((0,0),(0,0))
#    testp = (
