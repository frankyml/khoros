Feature request for this repository: Trino: parse CASE routine statements.

Details from the requester:

* feat(trino): parse CASE routine statements [CLAUDE]

Reuses exp.IfBlock per WHEN branch (only `this`/`true` populated) inside
a new, minimal exp.CaseStatement wrapper mirroring exp.Case's shape
(this=operand, ifs, default), rather than inventing a full new branch
type. The operand form ("CASE a WHEN 0 THEN ...") is normalized into an
EQ condition at parse time and unwrapped at generation time, so both
forms share one code path through _parse_routine_statements.

Confirmed against a real Trino instance that the docs' "Searched case"
synopsis (bare END) contradicts the docs' own worked example (END CASE);
only END CASE is actually accepted for either form.

* test(trino): cover no-operand/no-ELSE CASE and CASE as literal last statement

Closes two gaps in the phase-5 CASE test suite found while auditing test
sufficiency: the no-operand + no-ELSE combination wasn't exercised (only
its operand-form counterpart was), and no test had CASE immediately
followed by the enclosing END with nothing between them - the same
adjacent-END token-matching shape the BEGIN/IF phases already covered
for their own constructs. Both confirmed against a real Trino instance;
the second hits the same function-body completeness-check limitation
already documented on the IF phase (asserts grammar only).

* Update sqlglot/parsers/trino.py

Co-authored-by: Jo <46752250+georgesittas@users.noreply.github.com>

* refactor(trino): mirror _parse_case()/case_sql() instead of normalizing CASE branches

Per review feedback on #8068: drop the EQ-rewrite that normalized the
operand form ("CASE a WHEN 0 THEN ...") into WHEN a = 0 THEN ... at parse
time. Each branch now carries its raw match/condition value untouched,
exactly like the base parser's _parse_case()/case_sql() already do for
the CASE *expression* - only the branch bodies differ, since they're
;-delimited statement lists instead of single value expressions. Reuses
exp.If per branch (matching exp.Case's own ifs shape) instead of
exp.IfBlock, inside the same exp.CaseStatement wrapper.

* Update sqlglot/parsers/trino.py

---------

Co-authored-by: Jo <46752250+georgesittas@users.noreply.github.com>
