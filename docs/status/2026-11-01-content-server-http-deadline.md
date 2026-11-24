# Content-server HTTP deadline, 2026-11-01

One 45-second transport deadline now covers the anonymous authentication probe,
Digest/HTTPS Basic retries, connection attempts, TLS, response headers and body.
The watchdog interrupts trickling peers and is joined before return; expiry
cannot accept a partial response or authorize another send. Synchronous DNS
resolution remains outside interruption, with expiry enforced before connecting
after resolution. See the [regression evidence](../http-deadline.tdd.md).
No installed service or real library was changed.
