"""SQLGlot-based structural extraction; native strings remain authoritative."""
import re
import logging
import threading


class _QuietParser(logging.Filter):
    def __init__(self):
        super().__init__()
        self.thread = threading.get_ident()

    def filter(self, record):
        return record.thread != self.thread


def parse_sql(report, path, text, dialect, owner_id=None, locator='$sql'):
    """Add declarations, structural clauses and unbound reads; never run SQL."""
    raw_id = report.expression(path, locator, dialect or 'sql:unknown', text, owner_id,
                               interpretation='preserved_original')
    if not dialect:
        report.gap(path, 'sql.dialect_unknown', 'Choose a dialect from source evidence before interpreting SQL.')
        report.cover(path, 'partial')
        return
    if '{{' in text or '{%' in text or re.search(r'\b(EXECUTE\s+IMMEDIATE|EXEC\s*\(|CALL\s+)\b', text, re.I):
        report.gap(path, 'sql.dynamic', 'Templated or dynamic SQL is preserved; supply version-bound compiled evidence.')
        report.cover(path, 'partial')
        return
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.optimizer.scope import traverse_scope
        logger, quiet = logging.getLogger('sqlglot'), _QuietParser()
        logger.addFilter(quiet)
        try:
            trees = sqlglot.parse(text, read=dialect, error_level=sqlglot.ErrorLevel.RAISE)
        finally:
            logger.removeFilter(quiet)
    except ImportError:
        report.gap(path, 'sql.parser_dependency_missing', 'Install the pinned source-adapter dependencies; no semantic parsing was performed.')
        report.cover(path, 'partial')
        return
    except Exception:
        report.gap(path, 'sql.parse_error', 'The selected SQL parser could not interpret this statement; original SQL retained.')
        report.cover(path, 'partial')
        return
    for index, tree in enumerate(trees):
        if tree is None:
            continue
        loc = locator + '.statements[%d]' % index
        if isinstance(tree, exp.Command):
            report.gap(path, 'sql.unsupported_statement', 'Opaque command preserved without dependency or behavior claims.', loc)
            continue
        allowed = (exp.Query, exp.Create, exp.Insert, exp.Update, exp.Delete, exp.Merge)
        if not isinstance(tree, allowed):
            report.gap(path, 'sql.unsupported_statement', 'Statement is outside the structural extraction subset.', loc)
            continue
        if isinstance(tree, exp.Create) and str(tree.args.get('kind', '')).upper() not in ('TABLE', 'VIEW'):
            report.gap(path, 'sql.unsupported_create_kind', 'Only TABLE and VIEW declarations are structurally modeled; other CREATE statements are retained as source.', loc)
            continue
        target = tree.this if isinstance(tree, (exp.Create, exp.Insert, exp.Update, exp.Delete, exp.Merge)) else None
        schema = target if isinstance(target, exp.Schema) else None
        if schema is not None:
            target = schema.this
        target_name = '.'.join(p.sql(dialect=dialect) for p in target.parts) if isinstance(target, exp.Table) else None
        property_kinds = [type(p).__name__ for p in tree.args['properties'].expressions] if tree.args.get('properties') else []
        owner = owner_id or report.object(path, loc, 'relation' if target_name else 'query', target_name or path + ':' + str(index),
                    statement_kind=type(tree).__name__, dialect=dialect, operation=tree.args.get('kind'),
                    native_property_kinds=property_kinds,
                    properties=tree.args['properties'].sql(dialect=dialect) if tree.args.get('properties') else None)
        if set(property_kinds) & {'DynamicProperty', 'MaterializedProperty'}:
            report.gap(path, 'sql.native_materialization', 'Dynamic or materialized relation declaration retained; refresh, maintenance and runtime behavior require native review.', loc)
        if isinstance(tree, exp.Create) and not isinstance(tree.args.get('expression'), exp.Query):
            # LIKE/CLONE and other structural sources do not participate in a
            # SELECT scope. Preserve physical references without inventing reads.
            for table in tree.find_all(exp.Table):
                if table is target or table.find_ancestor(exp.Reference) is not None:
                    continue
                if isinstance(table.this, exp.Identifier):
                    report.dependency(path, loc, owner, '.'.join(p.sql(dialect=dialect) for p in table.parts),
                                      resolution='unresolved', kind='ddl_reference')
                report.gap(path, 'sql.non_query_ddl_dependency', 'Non-query DDL dependency retained; clone/copy semantics require native review.', loc)
        if schema is not None:
            primary_columns = {v.name for key in schema.find_all(exp.PrimaryKey) for v in key.expressions}
            for col_index, col in enumerate(schema.expressions):
                if isinstance(col, exp.ColumnDef):
                    report.object(path, loc + '.columns[%d]' % col_index, 'column', col.name,
                                  parent_id=owner, data_type=col.args['kind'].sql(dialect=dialect) if col.args.get('kind') else None,
                                  primary_key_declared=col.name in primary_columns or any(isinstance(c.args.get('kind'), exp.PrimaryKeyColumnConstraint) for c in col.args.get('constraints', [])),
                                  declaration=col.sql(dialect=dialect))
                else:
                    report.expression(path, loc + '.constraints[%d]' % col_index, dialect,
                                      col.sql(dialect=dialect), owner, interpretation='structural_constraint')
            for n, foreign_key in enumerate(schema.find_all(exp.ForeignKey)):
                reference = foreign_key.args.get('reference')
                referenced_schema = reference.this if isinstance(reference, exp.Reference) else None
                referenced_table = referenced_schema.this if isinstance(referenced_schema, exp.Schema) else referenced_schema
                if isinstance(referenced_table, exp.Table):
                    report.dependency(path, loc + '.foreign_keys[%d]' % n, owner,
                                      '.'.join(p.sql(dialect=dialect) for p in referenced_table.parts),
                                      kind='foreign_key', resolution='unresolved',
                                      source_columns=[v.name for v in foreign_key.expressions],
                                      target_columns=[v.name for v in referenced_schema.expressions] if isinstance(referenced_schema, exp.Schema) else [],
                                      enforcement='not_verified')
            for n, column in enumerate(schema.expressions):
                if not isinstance(column, exp.ColumnDef):
                    continue
                for j, constraint in enumerate(column.args.get('constraints', [])):
                    reference = constraint.args.get('kind')
                    if not isinstance(reference, exp.Reference):
                        continue
                    referenced_schema = reference.this
                    referenced_table = referenced_schema.this if isinstance(referenced_schema, exp.Schema) else referenced_schema
                    if isinstance(referenced_table, exp.Table):
                        report.dependency(path, loc + '.columns[%d].references[%d]' % (n, j), owner,
                                          '.'.join(p.sql(dialect=dialect) for p in referenced_table.parts),
                                          kind='foreign_key', resolution='unresolved', source_columns=[column.name],
                                          target_columns=[v.name for v in referenced_schema.expressions] if isinstance(referenced_schema, exp.Schema) else [],
                                          enforcement='not_verified')
        reads = set()
        try:
            for scope in traverse_scope(tree):
                for _, source in scope.sources.items():
                    if isinstance(source, exp.Table):
                        if isinstance(source.this, exp.Identifier):
                            start = source.this.meta.get('start')
                            literal = isinstance(start, int) and text[start:start + 1] == "'"
                            file_candidate = len(source.parts) == 1 and (literal or re.search(
                                r'(?i)(?:[/\\]|\.(?:parquet|csv|tsv|json|jsonl|ndjson)(?:\.gz)?$)', source.name))
                            databricks_path = dialect == 'databricks' and bool(re.search(r'[/\\]', source.name))
                            if (dialect == 'duckdb' and file_candidate) or databricks_path:
                                report.gap(path, 'sql.external_resource', 'Possible implicit file or format/path read retained in original SQL; not claimed as a catalogue table dependency. Resolve the external resource separately.', loc)
                            else:
                                reads.add('.'.join(p.sql(dialect=dialect) for p in source.parts))
                        else:
                            report.gap(path, 'sql.dynamic_relation', 'Table function or dynamic relation requires source-specific binding; not treated as a physical table.', loc)
        except Exception:
            report.gap(path, 'sql.scope_unresolved', 'Scope resolution failed; dependency completeness is not established.', loc)
        # DML without a query scope can include physical source references.
        if isinstance(tree, (exp.Update, exp.Delete, exp.Merge)):
            report.gap(path, 'sql.dml_behavior', 'DML effects and non-query dependencies require native evidence.', loc)
        for reference in sorted(reads):
            report.dependency(path, loc, owner, reference, resolution='unresolved', kind='reads_from')
        for kind in (exp.Join, exp.Where, exp.Having, exp.Group, exp.Qualify, exp.Window):
            for n, node in enumerate(tree.find_all(kind)):
                report.expression(path, loc + '.' + kind.__name__ + '[%d]' % n, dialect,
                                  node.sql(dialect=dialect), owner, interpretation='structural', expression_kind=kind.__name__, original_expression_id=raw_id)
        for n, node in enumerate(tree.find_all(exp.Select)):
            for j, projection in enumerate(node.expressions):
                report.expression(path, loc + '.select[%d].projection[%d]' % (n, j), dialect,
                                  projection.sql(dialect=dialect), owner, output_name=projection.alias_or_name,
                                  interpretation='structural', original_expression_id=raw_id)
        if any(star.find_ancestor(exp.Count) is None for star in tree.find_all(exp.Star)):
            report.gap(path, 'sql.wildcard', 'Wildcard columns require the matching physical catalogue; no expanded column lineage is claimed.', loc)
    report.cover(path, 'parsed', 'Structural SQL extraction only; native behavior and column bindings remain unverified.')
