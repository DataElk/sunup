"""Reading cached payloads off disk.

This is a READ-ONLY stand-in for the M0 client. It never opens a socket. When a
payload the pipeline needs is not on disk it raises OfflineDataUnavailable naming
the exact call that would produce it, rather than substituting a plausible value.

When M0 lands, its cache should sit behind the same accessors so nothing
downstream changes.
"""
