# Source browser busy response

When the browser listener is at capacity, it now sends the busy response and
half-closes its write side before draining a bounded amount of incoming data.
The drain has a short deadline so an idle client cannot hold the listener
indefinitely. The request capacity and existing request-size limits are unchanged.

Regression coverage exercises an upload still in progress when the busy reply
arrives and an idle client followed by another connection. This is a transport
fix; it does not change browser admission or activate a service.
