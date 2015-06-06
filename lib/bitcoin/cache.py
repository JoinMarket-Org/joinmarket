#!/usr/bin/env python2

from shelve import DbfilenameShelf as Sh
import time


class Cache(Sh):
    '''
    Validity works only with get() and put() methods
    '''

    def __init__(self, filename='blockchain.cache', validity=300):
        Sh.__init__(self, filename)
        self.validity = validity

    def __enter__(self):
        return self

    def __exit__(self, exc_t, exc_v, trace):
        self.close()

    def clean():
        since = time.time() - self.validity
        for k, (t, _) in self.items():
            if t < since:
                del self[k]

    def get(self, key, default=None):
        since = time.time() - self.validity
        if key in self:
            t, v = self[key]
            if t >= since:
                return v
        return default

    def put(self, key, value):
        self[key] = (time.time(), value)


if __name__ == "__main__":

    with Cache('/tmp/test.cache', 1) as c:
        print c.get('test')
        c.put('test', 1)
        print c.get('test')
        time.sleep(2)
        print c.get('test')
