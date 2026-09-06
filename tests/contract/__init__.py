"""Contract tests - the shape of the API, asserted without running it.

`01-foundations.md` §8 puts one here (`T-FOUND-08.4`), and `FOUND-13` adds the
generated-client checks. They read the route table rather than call it, which is
what lets them assert about routes that do not exist yet without pretending they
do.
"""
