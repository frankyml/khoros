Feature request for this repository: Parser: support mixed-operation `ALTER`s..

Details from the requester:

* feat(parser)!: support mixed-operation `ALTER`s.

Both MySQL and PostgreSQL support mixed-operation `ALTER`s, which are
not currently supported by `sqlglot`, such as a `DROP` and `ADD` in the
same statement. For example, the following syntax is valid in MySQL and
PostgreSQL, but currently parses as `Command`:

```
ALTER TABLE t
    ADD COLUMN a INT NOT NULL,
    DROP COLUMN b;
```

With this commit, these will now parse as `Alter`.

From what I can tell, most dialects seem to support mixed-operation
syntax like this. However, some, like Snowflake, do not. As such, I
opted to hide this behaviour behind `ALTER_TABLE_MIXED_ACTIONS`, which
is only enabled in MySQL and PostgreSQL (and derivatives) in this
commit.

One specific call-out in this change is the T-SQL behaviour of rewriting
a `RENAME` to `sp_rename`. The mixed-operation parsing broke this:
instead of carrying along the additional operations, they were truncated
with no warning. This commit emits a warning instead of truncating, but
I think a comprehensive change is best handled by somebody that's more
familiar with T-SQL.

While I think that this commit applies correct parsing behaviour in most
cases, I do suspect it may add regressions like the T-SQL one in some
other dialects that aren't currently tested.

* fix(parser): Parse keyword-named coulmn in `ALTER`.

Column and indexes named as keywords parse as names. PostgreSQL `ALTER
COLUMN` needs `TYPE` to change types.

* refactor loop

* revert tsql

* refactor tests

* fix(mysql): Parse `ADD FULLTEXT` as index.

Parse `FULLTEXT` and `SPATIAL` indexes as indexes rather than columns.

* refactor if logic

---------

Co-authored-by: geooo109 <geomichas96@gmail.com>
