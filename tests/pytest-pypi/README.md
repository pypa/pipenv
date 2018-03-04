# pytest-httpbin

[![Build Status](https://travis-ci.org/kevin1024/pytest-httpbin.svg?branch=master)](https://travis-ci.org/kevin1024/pytest-httpbin)

[httpbin](https://httpbin.org/) is an amazing web service for testing HTTP libraries.  It has several great endpoints that can test pretty much everything you need in a HTTP library.  The only problem is: maybe you don't want to wait for your tests to travel across the Internet and back to make assertions against a remote web service (speed), and maybe you want to work offline (convenience).

Enter **pytest-httpbin**.  Pytest-httpbin creates a [pytest fixture](http://pytest.org/latest/fixture.html) that is dependency-injected into your tests.  It automatically starts up a HTTP server in a separate thread running httpbin and provides your test with the URL in the fixture.  Check out this example:

```python
def test_that_my_library_works_kinda_ok(httpbin):
    assert requests.get(httpbin.url + '/get').status_code == 200
```

This replaces a test that might have looked like this before:

```python
def test_that_my_library_works_kinda_ok():
    assert requests.get('http://httpbin.org/get').status_code == 200
```

If you're making a lot of requests to httpbin, it can radically speed up your tests.

![demo](http://i.imgur.com/heNOQLP.gif)


# HTTPS support

pytest-httpbin also supports HTTPS:

```python
def test_that_my_library_works_kinda_ok(httpbin_secure):
    assert requests.get(httpbin_secure.url + '/get/').status_code == 200
```

It's actually starting 2 web servers in separate threads in the background: one HTTP and one HTTPS. The servers are started on a random port (see below for fixed port support), on the loopback interface on your machine. Pytest-httpbin includes a self-signed certificate.  If your library verifies certificates against a CA (and it should), you'll have to add the CA from pytest-httpbin.  The path to the pytest-httpbin CA bundle can by found like this `python -m pytest_httpbin.certs`.

For example in requests, you can set the `REQUESTS_CA_BUNDLE` python path.  You can run your tests like this:

```bash
REQUESTS_CA_BUNDLE=`python -m pytest_httpbin.certs` py.test tests/
```

# API of the injected object

The injected object has the following attributes:

  * url
  * port
  * host

and the following methods:

  * join(string): Returns the results of calling `urlparse.urljoin` with the url from the injected server automatically applied as the first argument.  You supply the second argument

Also, I defined `__add__` on the object to append to `httpbin.url`.  This means you can do stuff like `httpbin + '/get'` instead of `httpbin.url + '/get'`.

## Testing both HTTP and HTTPS endpoints with one test

If you ever find yourself needing to test both the http and https version of and endpoint, you can use the `httpbin_both` funcarg like this:


```python
def test_that_my_library_works_kinda_ok(httpbin_both):
    assert requests.get(httpbin_both.url + '/get/').status_code == 200
```

Through the magic of pytest parametrization, this function will actually execute twice: once with an http url and once with an https url.

## Using pytest-httpbin with unittest-style test cases

I have provided 2 additional fixtures to make testing with class-based tests easier.  I have also provided a couple decorators that provide some syntactic sugar around the pytest method of adding the fixtures to class-based tests.  Just add the `use_class_based_httpbin` and/or `use_class_based_httpbin_secure` class decorators to your class, and then you can access httpbin using self.httpbin and self.httpbin_secure.

```python
import pytest_httpbin

@pytest_httpbin.use_class_based_httpbin
@pytest_httpbin.use_class_based_httpbin_secure
class TestClassBassedTests(unittest.TestCase):
    def test_http(self):
        assert requests.get(self.httpbin.url + '/get').response

    def test_http_secure(self):
        assert requests.get(self.httpbin_secure.url + '/get').response
```

## Running the server on fixed port

Sometimes a randomized port can be a problem. Worry not, you can fix the port number to a desired value with the `HTTPBIN_HTTP_PORT` and `HTTPBIN_HTTPS_PORT` environment variables. If those are defined during pytest plugins are loaded, `httbin` and `httpbin_secure` fixtures will run on given ports. You can run your tests like this:

```bash
HTTPBIN_HTTP_PORT=8080 HTTPBIN_HTTPS_PORT=8443 py.test tests/
```

## Installation

All you need to do is this:

```bash
pip install pytest-httpbin
```

and your tests executed by pytest all will have access to the `httpbin` and `httpbin_secure` funcargs.  Cool right?

## Support and dependencies

pytest-httpbin suports Python 2.6, 2.7, 3.4, and pypy.  It will automatically install httpbin and flask when you install it from pypi.

[httpbin](https://github.com/kennethreitz/httpbin) itself does not support python 2.6 as of version 0.6.0, when the Flask-common dependency was added.  If you need python 2.6 support pin the httpbin version to 0.5.0

## Running the pytest-httpbin test suite

If you want to run pytest-httpbin's test suite, you'll need to install requests and pytest, and then use the ./runtests.sh script.

```bash
pip install pytest
/.runtests.sh
```

Also, you can use tox to run the tests on all supported python versions:

```bash
pip install tox
tox
```

## Changelog

* 0.3.0
  * Allow to run httpbin on fixed port using environment variables (thanks @hroncok)
  * Allow server to be thread.join()ed (thanks @graingert)
  * Add support for Python 3.6 (thanks @graingert)
* 0.2.3: 
  * Another attempt to fix #32 (Rare bug, only happens on Travis)
* 0.2.2: 
  * Fix bug with python3
* 0.2.1:
  * Attempt to fix strange, impossible-to-reproduce bug with broken SSL certs
    that only happens on Travis (#32) [Bad release, breaks py3]
* 0.2.0:
  * Remove threaded HTTP server.  I built it for Requests, but they deleted
    their threaded test since it didn't really work very well.  The threaded
    server seems to cause some strange problems with HTTP chunking, so I'll
    just remove it since nobody is using it (I hope)
* 0.1.1:
  * Fix weird hang with SSL on pypy (again)
* 0.1.0:
  * Update server to use multithreaded werkzeug server
* 0.0.7:
  * Update the certificates (they expired)
* 0.0.6:
  * Fix an issue where pypy was hanging when a request was made with an invalid
    certificate
* 0.0.5:
  * Fix broken version parsing in 0.0.4
* 0.0.4:
  * **Bad release: Broken version parsing**
  * Fix `BadStatusLine` error that occurs when sending multiple requests
    in a single session (PR #16). Thanks @msabramo!
  * Fix #9 ("Can't be installed at the same time than pytest?") (PR
    #14). Thanks @msabramo!
  * Add `httpbin_ca_bundle` pytest fixture. With this fixture there is
    no need to specify the bundle on every request, as it will
    automatically set `REQUESTS_CA_BUNDLE` if using
    [requests](http://docs.python-requests.org/). And you don't have to
    care about where it is located (PR #8). Thanks @t-8ch!
* 0.0.3: Add a couple test fixtures to make testing old class-based test suites
  easier
* 0.0.2: Fixed a couple bugs with the wsgiref server to bring behavior in line
  with httpbin.org, thanks @jakubroztocil for the bug reports
* 0.0.1: Initial release

## License

The MIT License (MIT)

Copyright (c) 2014-2015 Kevin McCarthy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
