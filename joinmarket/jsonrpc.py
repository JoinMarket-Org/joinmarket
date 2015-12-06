# Copyright (C) 2013,2015 by Daniel Kraft <d@domob.eu>
# Copyright (C) 2014 by phelix / blockchained.com
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import base64
import httplib
import json


class JsonRpcError(Exception):
    """
  The called method returned an error in the JSON-RPC response.
  """

    def __init__(self, obj):
        self.code = obj["code"]
        self.message = obj["message"]


class JsonRpcConnectionError(Exception):
    """
  Error thrown when the RPC connection itself failed.  This means
  that the server is either down or the connection settings
  are wrong.
  """

    pass


class JsonRpc(object):
    """
  Simple implementation of a JSON-RPC client that is used
  to connect to Bitcoin.
  """

    def __init__(self, host, port, user, password):
        self.host = host
        self.port = port
        self.authstr = "%s:%s" % (user, password)

        self.queryId = 1

    def queryHTTP(self, obj):
        """
    Send an appropriate HTTP query to the server.  The JSON-RPC
    request should be (as object) in 'obj'.  If the call succeeds,
    the resulting JSON object is returned.  In case of an error
    with the connection (not JSON-RPC itself), an exception is raised.
    """

        headers = {}
        headers["User-Agent"] = "joinmarket"
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "application/json"
        headers["Authorization"] = "Basic %s" % base64.b64encode(self.authstr)

        body = json.dumps(obj)

        try:
            conn = httplib.HTTPConnection(self.host, self.port)
            conn.request("POST", "", body, headers)
            response = conn.getresponse()

            if response.status == 401:
                conn.close()
                raise JsonRpcConnectionError(
                    "authentication for JSON-RPC failed")

            # All of the codes below are 'fine' from a JSON-RPC point of view.
            if response.status not in [200, 404, 500]:
                conn.close()
                raise JsonRpcConnectionError("unknown error in JSON-RPC")

            data = response.read()
            conn.close()

            return json.loads(data)

        except JsonRpcConnectionError as exc:
            raise exc
        except Exception as exc:
            raise JsonRpcConnectionError("JSON-RPC connection failed. Err:" +
                                         repr(exc))

    def call(self, method, params):
        """
    Call a method over JSON-RPC.
    """

        currentId = self.queryId
        self.queryId += 1

        request = {"method": method, "params": params, "id": currentId}
        response = self.queryHTTP(request)

        if response["id"] != currentId:
            raise JsonRpcConnectionError("invalid id returned by query")

        if response["error"] is not None:
            print response["error"]
            raise JsonRpcError(response["error"])

        return response["result"]
