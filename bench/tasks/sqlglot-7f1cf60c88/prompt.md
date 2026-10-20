Feature request for this repository: Parser: Make `ALTER` actions optional..

Details from the requester:

* feat(parser)!: Make `ALTER` actions optional.

MySQL allows for an `ALTER TABLE` to consist of only options without any
actions. For example, `ALTER TABLE t FORCE` or `ALTER TABLE COMMENT='hi'
AUTO_INCREMENT=5`. Today, these are parsed in such a way that the first
option is an `action`, which leads to inconsistent parse trees:

|DDL|actions|options|
|-|-|-|
|ALTER TABLE t AUTO_INCREMENT=10, COMMENT='hi'|AutoIncrementProperty|SchemaCommentProperty|
|ALTER TABLE t COMMENT='hi', AUTO_INCREMENT=10|SchemaCommentProperty|AutoIncrementProperty|

This commit makes `actions` optional when `ALTER_TABLE_REQUIRES_ACTION`
is disabled, allowing the same DDL to parse as an empty action with two
options.

I had previously tried to approach the same problem by adding `COMMENT`
and `AUTO_INCREMENT` into the `ALTER_PARSERS`, which, in retrospect,
wasn't the right approach.

* refactor logic

* push ALTER OPTIONS in mysql

* refactor ALTER partition options

* refactor test

---------

Co-authored-by: geooo109 <geomichas96@gmail.com>
