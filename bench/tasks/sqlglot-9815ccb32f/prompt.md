Feature request for this repository: Trino: parse routine characteristics for inline UDFs.

Details from the requester:

* feat(trino): parse routine characteristics for inline UDFs [CLAUDE]

LANGUAGE, DETERMINISTIC/NOT DETERMINISTIC, CALLED/RETURNS NULL ON NULL
INPUT, SECURITY DEFINER/INVOKER, and COMMENT now parse and generate
correctly for WITH FUNCTION inline UDFs (#7934 was PR 1 of ~7).

* docs(trino): explain why SQL SECURITY is popped from Trino's tokenizer

Trino has no SQL SECURITY clause of its own; the merged base keyword
otherwise swallows the SQL in LANGUAGE SQL SECURITY DEFINER.

* feat(trino): parse the optional WITH (...) clause on inline UDFs

Per @treysp's review: the routine characteristics and the trailing
WITH (property_name = expression, ...) clause need separate parsing,
since WITH's entries are arbitrary key/value pairs rather than one of
the fixed PROPERTY_PARSERS keywords the rest of the characteristics
loop matches on. FunctionSpecification gets a new characteristics arg
for the former; the existing properties arg now holds the WITH set.

* fix(trino): address georgesittas's review feedback

- _parse_property() now intercepts NOT DETERMINISTIC directly instead
  of merging it into one token at the tokenizer level (as BigQuery
  does): the merged token misparsed SELECT NOT deterministic FROM t,
  silently swallowing NOT as a boolean operator. Scoped to Trino only.
- Clarify/trim the two comments flagged as unclear or inaccurate.
- Note in test_inline_udf that the SECURITY / WITH (...) cases assert
  grammar round-tripping, not that Trino accepts that combination on
  an inline SQL-language UDF specifically (confirmed against a real
  Trino instance in review).
