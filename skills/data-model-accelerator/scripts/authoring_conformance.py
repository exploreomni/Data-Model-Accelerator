"""Read-only structural conformance, including CTE projection and dependency checks.

An expression match is a static contract comparison, never business acceptance.
Unknown mappings, dynamic templates and physical stars remain explicit gaps.
"""
from pathlib import Path

from ae_common import require
from authoring_evidence import finding, validate_contract
from authoring_provenance import _read, mask_static_dbt_sql, _expression_hash


def check_conformance(root, contract, paths, dialect):
    contract = validate_contract(contract)
    findings, graph = [], {}
    models = contract['models']
    stems = {}
    for row in models:
        if row['path']:
            stems.setdefault(Path(row['path']).stem, []).append(row['id'])
    try:
        import sqlglot
        from sqlglot import exp
        from sqlglot.optimizer.scope import build_scope, Scope
    except ImportError:
        return [finding('conformance_parser_unavailable', 'unsupported')]

    def columns(scope, active):
        require(scope is not None and id(scope) not in active, 'Recursive or absent scope')
        require(not scope.outer_columns, 'CTE or derived-table column aliases require native binding')
        active = active | {id(scope)}
        require(isinstance(scope.expression, exp.Select), 'Set projection unsupported')
        result = []
        for projection in scope.expression.selects:
            if projection.is_star:
                star = projection.this if isinstance(projection, exp.Column) else projection
                require(not any(star.args.values()), 'Star modifiers unsupported')
                selected = scope.selected_sources
                table = projection.table if isinstance(projection, exp.Column) else None
                sources = [selected[table][1]] if table in selected else [s for _, s in selected.values()] if table is None else []
                require(sources and all(isinstance(s, Scope) for s in sources), 'Physical star needs native catalogue expansion')
                for source in sources:
                    result.extend(columns(source, active))
            else:
                name = projection.alias_or_name
                require(bool(name), 'Unnamed projection needs native output metadata')
                result.append(name)
        require(len(result) == len(set(result)), 'Ambiguous output columns')
        return result

    for model in models:
        path, model_id = model['path'], model['id']
        def add(code, status, field=None):
            findings.append(finding(code, status, model_id=model_id, path=path, field=field))
        if path is None or path not in paths:
            add('model_file_binding_unknown', 'not_run'); continue
        if Path(path).suffix.lower() != '.sql':
            add('model_conformance_format_unsupported', 'unsupported'); continue
        try:
            text, _, _ = _read(Path(root), path)
            masked, calls, gaps = mask_static_dbt_sql(text)
            require(not gaps, 'Template coverage incomplete')
            trees = [t for t in sqlglot.parse(masked, read=dialect) if t is not None]
            require(len(trees) == 1, 'Multiple execution units require individual contracts')
            tree = trees[0]
            if isinstance(tree, exp.Create): tree = tree.expression
            require(isinstance(tree, exp.Select), 'Unsupported model statement')
            scope = build_scope(tree)
        except Exception:
            add('model_parse_unsupported', 'unsupported'); continue
        add('model_syntax_checked', 'passed')
        try:
            observed = columns(scope, set())
            if model['columns'] is None:
                add('output_contract_unknown', 'not_run')
            elif observed == model['columns']:
                add('output_columns_match', 'passed')
            elif [x.casefold() for x in observed] == [x.casefold() for x in model['columns']]:
                add('output_identifier_case_requires_native_binding', 'unsupported')
            else:
                add('output_columns_differ', 'failed')
        except (ValueError, KeyError, TypeError, RecursionError):
            add('output_projection_unsupported', 'unsupported')
        call_names = {c['identifier']: c for c in calls}
        dependencies, visited = set(), set()
        try:
            def visit(current):
                require(current is not None, 'Unknown dependency scope')
                if id(current) in visited: return
                visited.add(id(current))
                for _, source in current.selected_sources.values():
                    if isinstance(source, Scope):
                        visit(source)
                    elif isinstance(source, exp.Table):
                        call = call_names.get(source.name) if not source.catalog and not source.db else None
                        if call and call['name'] == 'ref':
                            # Package-qualified refs cannot be assigned to a
                            # local model using its short name alone.
                            candidates = (stems.get(call['arguments'][-1], [])
                                          if len(call['arguments']) == 1 and call['version'] is None else [])
                            require(len(candidates) <= 1, 'Ambiguous model identity')
                            dependencies.add(candidates[0] if candidates else call['key'])
                        elif call:
                            dependencies.add(call['key'])
                        else:
                            relation = source.copy(); relation.set('alias', None)
                            dependencies.add('table:' + relation.sql(dialect=dialect))
                    else: raise ValueError('Unsupported relation')
                for child in current.subquery_scopes: visit(child)
            visit(scope)
            graph[model_id] = dependencies & {m['id'] for m in models}
            if model['depends_on'] is None:
                add('dependency_contract_unknown', 'not_run')
            else:
                add('dependencies_match' if dependencies == set(model['depends_on']) else 'dependencies_differ',
                    'passed' if dependencies == set(model['depends_on']) else 'failed')
        except (ValueError, KeyError, TypeError, RecursionError):
            add('dependency_coverage_unsupported', 'unsupported')
        selected = {p.alias_or_name: p for p in tree.selects}
        for column, expected in model.get('expressions', {}).items():
            expression = selected.get(column)
            if expression is None:
                add('expression_projection_unknown', 'unsupported', column); continue
            if isinstance(expression, exp.Alias): expression = expression.this
            try:
                matches = _expression_hash(expression.sql(), dialect) == _expression_hash(expected, dialect)
                add('expression_matches' if matches else 'expression_differs', 'passed' if matches else 'failed', column)
            except Exception:
                add('expression_comparison_unsupported', 'unsupported', column)
    pending = {node: set(parents) & set(graph) for node, parents in graph.items()}
    while pending:
        ready = {node for node, parents in pending.items() if not parents}
        if not ready:
            findings.extend(finding('observed_dependency_cycle', 'failed', model_id=node) for node in sorted(pending))
            break
        pending = {node: parents - ready for node, parents in pending.items() if node not in ready}
    return findings
