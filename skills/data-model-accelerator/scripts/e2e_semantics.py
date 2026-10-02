"""Definition-driven, deliberately bounded offline Looker/Omni SQL compilation.

This is a synthetic regression adapter, not either product's native compiler or
validator. It supports one Looker SQL-derived view, or two physical Omni views
with one declared many-to-one left join; scalar dimensions; filtered count/sum;
compound arithmetic, COALESCE and NULLIF; exact tenant access attributes; and
the supplied dashboard's equality/date filters. Unsupported model constructs
fail closed. Warehouse SQL execution, grain checks, and tenant provisioning are
outside this module. No expected-output/oracle files are read.

Runtime dates are ISO dates with a half-open [start_date, end_date) interval.
Dashboard "YYYY/MM/DD to YYYY/MM/DD" defaults include the final calendar date.
Runtime grouping controls output ordering; the original tile sort is validated,
and its row limit is retained. Source SUM(empty) remains NULL unless the source
definition itself explicitly supplies a COALESCE.
"""

from datetime import date, timedelta
import json
from pathlib import Path
import re

try:
    import lkml
    import sqlglot
    from sqlglot import exp
    import yaml
except ImportError:  # Keep the dependency-free base test suite importable.
    lkml = sqlglot = exp = yaml = None


class SemanticCompileError(ValueError):
    """A definition or parameter falls outside the verified offline subset."""


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\}")
_OUTPUTS = {"invoice_count": "invoice_count", "net_cents_sum": "net_cents",
            "paid_cents_sum": "paid_cents", "payment_rate": "payment_rate"}
_DECORATION = {"label", "description", "hidden", "group_label", "value_format_name", "value_format"}


def _require_dependencies():
    if any(module is None for module in (lkml, sqlglot, exp, yaml)):
        raise SemanticCompileError("Offline compilation requires lkml, sqlglot, and PyYAML")


def _mapping(value, where):
    if not isinstance(value, dict):
        raise SemanticCompileError(f"{where}: expected an object")
    return value


def _keys(value, allowed, where):
    _mapping(value, where)
    unknown = set(value) - set(allowed)
    if unknown:
        raise SemanticCompileError(f"{where}: unsupported keys: {', '.join(sorted(unknown))}")


def _name(value, where):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise SemanticCompileError(f"{where}: expected a simple identifier")
    return value


def _literal(value):
    if not isinstance(value, str):
        raise SemanticCompileError("Only exact string filter values are supported")
    return exp.Literal.string(value).sql(dialect="snowflake")


def _sql_expression(sql, *, allow_aggregates, aliases, qualify=None, physical_case=False):
    if not isinstance(sql, str) or not sql.strip() or any(t in sql for t in ("${", "{{", "{%", ";", "--", "/*")):
        raise SemanticCompileError("Empty SQL, unresolved references, Liquid, statements, or SQL comments are unsupported")
    try:
        nodes = sqlglot.parse(sql, read="snowflake")
    except Exception as error:
        raise SemanticCompileError(f"Unsupported SQL expression: {error}") from error
    if len(nodes) != 1 or nodes[0] is None:
        raise SemanticCompileError("Expected one scalar SQL expression")
    tree = nodes[0]
    allowed = {exp.Column, exp.Identifier, exp.Literal, exp.Add, exp.Sub, exp.Mul,
               exp.Div, exp.Neg, exp.Paren, exp.Coalesce, exp.Nullif, exp.Null,
               exp.Boolean, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE,
               exp.And, exp.Or, exp.Not, exp.Is, exp.Case, exp.If}
    if allow_aggregates:
        allowed |= {exp.Sum, exp.Count, exp.Star}
    for node in tree.walk():
        if type(node) not in allowed:
            raise SemanticCompileError(f"Unsupported SQL expression construct: {type(node).__name__}")
        if isinstance(node, exp.Column):
            if node.db or node.catalog:
                raise SemanticCompileError("Physical expressions cannot escape the declared view")
            if node.table and node.table not in aliases:
                raise SemanticCompileError(f"Unknown SQL view alias: {node.table}")
            if physical_case and node.this.args.get("quoted") and node.name != node.name.upper():
                raise SemanticCompileError(f"Quoted physical column {node.name!r} is not uppercase; Snowflake case must match the fixture")
            if not node.table:
                if qualify is None:
                    raise SemanticCompileError(f"Unbound physical column in compound SQL: {node.name}")
                node.set("table", exp.to_identifier(qualify, quoted=True))
            if allow_aggregates and not node.find_ancestor(exp.AggFunc):
                raise SemanticCompileError(f"Unaggregated physical column in compound SQL: {node.name}")
    # Reject nested aggregation even when it occurs through modeled references.
    for aggregate in tree.find_all(exp.AggFunc):
        if any(isinstance(child, exp.AggFunc) for child in aggregate.walk() if child is not aggregate):
            raise SemanticCompileError("Nested aggregation is unsupported")
    return tree.sql(dialect="snowflake")


def _load_yaml(path):
    try:
        class UniqueSafeLoader(yaml.SafeLoader):
            pass

        def unique_mapping(loader, node, deep=False):
            result = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in result:
                    raise SemanticCompileError(f"Duplicate YAML key {key!r} in {path}")
                result[key] = loader.construct_object(value_node, deep=deep)
            return result

        UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
        return yaml.load(Path(path).read_text(), Loader=UniqueSafeLoader)
    except (OSError, yaml.YAMLError) as error:
        raise SemanticCompileError(f"Cannot read YAML {path}: {error}") from error


def _one(values, where):
    if not isinstance(values, list) or len(values) != 1:
        raise SemanticCompileError(f"{where}: exactly one declaration is required")
    return values[0]


def _named(items, where):
    if not isinstance(items, list):
        raise SemanticCompileError(f"{where}: expected a field list")
    answer = {}
    for item in items:
        name = _name(_mapping(item, where).get("name"), where)
        if name in answer:
            raise SemanticCompileError(f"{where}: duplicate field {name}")
        answer[name] = item
    return answer


class _Model:
    def __init__(self, kind, base, views, access, report, source_sql=None, relation=None):
        self.kind, self.base, self.views = kind, base, views
        self.access, self.report = access, report
        self.source_sql, self.relation = source_sql, relation
        self.cache = {}

    def field(self, ref, current=None):
        if not isinstance(ref, str):
            raise SemanticCompileError("Model field references must be strings")
        parts = ref.split(".")
        if len(parts) == 1:
            parts.insert(0, current or self.base)
        if len(parts) != 2:
            raise SemanticCompileError(f"Malformed field reference: {ref}")
        view, field = (_name(part, "field reference") for part in parts)
        if view not in self.views:
            raise SemanticCompileError(f"Unknown or unjoined view: {view}")
        definition = self.views[view]
        if field in definition["dimensions"]:
            return view, field, "dimension", definition["dimensions"][field]
        if field in definition["measures"]:
            return view, field, "measure", definition["measures"][field]
        raise SemanticCompileError(f"Unknown modeled field: {view}.{field}")

    def resolve(self, ref, current=None, stack=()):
        view, field, kind, definition = self.field(ref, current)
        key = f"{view}.{field}"
        if key in stack:
            raise SemanticCompileError(f"Cyclic field reference: {' -> '.join((*stack, key))}")
        if key in self.cache:
            return self.cache[key]
        trail = (*stack, key)
        if kind == "dimension":
            sql = self.substitute(definition.get("sql"), view, trail, dimensions_only=True)
            result = _sql_expression(sql, allow_aggregates=False, aliases=self.views,
                                     qualify=view, physical_case=self.kind == "omni")
        else:
            aggregate = definition.get("type") if self.kind == "looker" else definition.get("aggregate_type")
            filters = self.measure_filters(definition, view, trail)
            sql = definition.get("sql")
            if aggregate in ("sum", "count"):
                if aggregate == "count" and sql is None:
                    inner = "1" if filters else "*"
                else:
                    inner = self.substitute(sql, view, trail, dimensions_only=True)
                    inner = _sql_expression(inner, allow_aggregates=False, aliases=self.views,
                                            qualify=view, physical_case=self.kind == "omni")
                if filters:
                    inner = f"CASE WHEN {' AND '.join(filters)} THEN {inner} END"
                result = f"{aggregate.upper()}({inner})"
            elif aggregate in (None, "number"):
                if filters:
                    raise SemanticCompileError(f"{key}: filters on compound measures are unsupported")
                if not isinstance(sql, str) or not _REFERENCE.search(sql):
                    raise SemanticCompileError(f"{key}: compound measures must reference modeled measures")
                sql = self.substitute(sql, view, trail, measures_only=True)
                result = _sql_expression(sql, allow_aggregates=True, aliases=self.views,
                                         physical_case=self.kind == "omni")
            else:
                raise SemanticCompileError(f"{key}: unsupported aggregate type {aggregate!r}")
        self.cache[key] = result
        return result

    def substitute(self, sql, current, stack, dimensions_only=False, measures_only=False):
        if not isinstance(sql, str):
            raise SemanticCompileError(f"{'.'.join((current, stack[-1].split('.')[-1]))}: missing SQL")
        if self.kind == "looker":
            sql = sql.replace("${TABLE}", f'"{current}"')

        def replace(match):
            ref = match.group(1)
            view, field, kind, _ = self.field(ref, current)
            if dimensions_only and kind != "dimension":
                raise SemanticCompileError(f"Scalar or aggregate input references a measure: {ref}")
            if measures_only and kind != "measure":
                raise SemanticCompileError(f"Compound measure references an unaggregated dimension: {ref}")
            return f"({self.resolve(f'{view}.{field}', stack=stack)})"

        return _REFERENCE.sub(replace, sql)

    def exact_filter(self, ref, value, current=None, stack=()):
        _, _, kind, _ = self.field(ref, current)
        if kind != "dimension":
            raise SemanticCompileError(f"Filters must bind to dimensions: {ref}")
        # Looker's filter language uses punctuation for operators/lists/wildcards.
        # This subset supports exact single values only, including runtime segment
        # values separately validated/quoted by compile().
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_ -]+", value):
            raise SemanticCompileError(f"Unsupported exact filter value for {ref}: {value!r}")
        if value.upper() in {"NULL", "NOT NULL", "EMPTY", "NOT EMPTY"} or value.startswith(("-", "NOT ")):
            raise SemanticCompileError(f"Unsupported filter operator for {ref}: {value!r}")
        return f"({self.resolve(ref, current, stack)}) = {_literal(value)}"

    def measure_filters(self, definition, view, stack):
        if self.kind == "looker":
            blocks = definition.get("filters__all", [])
            if not blocks:
                return []
            pairs = _one(blocks, "Looker measure filters")
            if not isinstance(pairs, list):
                raise SemanticCompileError("Looker measure filters must be a list")
            filters = {}
            for pair in pairs:
                if not isinstance(pair, dict) or len(pair) != 1:
                    raise SemanticCompileError("Unsupported Looker measure filter structure")
                ref, value = next(iter(pair.items()))
                if ref in filters:
                    raise SemanticCompileError(f"Duplicate measure filter: {ref}")
                filters[ref] = value
        else:
            filters = {}
            for ref, condition in _mapping(definition.get("filters", {}), "Omni measure filters").items():
                if not isinstance(condition, dict) or set(condition) != {"is"}:
                    raise SemanticCompileError(f"{ref}: only the Omni 'is' filter operator is supported")
                filters[ref] = condition["is"]
        return [self.exact_filter(ref, value, view, stack) for ref, value in filters.items()]

    def validate(self):
        for view, fields in self.views.items():
            for kind in ("dimensions", "measures"):
                for name in fields[kind]:
                    self.resolve(f"{view}.{name}")
        rule = _one(self.access, "Tenant access policy")
        _keys(rule, {"field", "user_attribute"}, "Tenant access policy")
        if rule.get("field") != f"{self.base}.tenant_id" or rule.get("user_attribute") != "tenant_id":
            raise SemanticCompileError("Tenant access policy must bind the base view tenant_id to user attribute tenant_id")
        security_column = sqlglot.parse_one(self.resolve(rule["field"]), read="snowflake")
        if not isinstance(security_column, exp.Column) or security_column.table != self.base or security_column.name.upper() != "TENANT_ID":
            raise SemanticCompileError("Tenant access field must map directly to the base physical TENANT_ID column")
        self._validate_report()

    def _validate_report(self):
        report = self.report
        _keys(report, {"model", "explore", "filters", "element"}, "Report context")
        if report.get("explore") != self.base:
            raise SemanticCompileError("Report explore does not match the semantic base view")
        _name(report.get("model"), "Report model")
        element = _mapping(report.get("element"), "Report element")
        _keys(element, {"name", "title", "model", "explore", "type", "fields", "filters", "listen", "sorts", "limit"}, "Report element")
        if element.get("model", report["model"]) != report["model"] or element.get("explore", self.base) != self.base:
            raise SemanticCompileError("Dashboard tile model/explore binding is inconsistent")
        fields = element.get("fields")
        if not isinstance(fields, list) or len(fields) != len(set(fields)):
            raise SemanticCompileError("Report fields must be a unique field list")
        for field in fields:
            self.field(field)
        required = {f"{self.base}.{field}" for field in _OUTPUTS}
        if not required.issubset(fields):
            raise SemanticCompileError("Report tile must expose all four requested output measures")
        sorts = element.get("sorts", [])
        if not isinstance(sorts, list):
            raise SemanticCompileError("Report sorts must be a field list")
        for field in sorts:
            if field not in fields or self.field(field)[2] != "dimension":
                raise SemanticCompileError(f"Unsupported report sort: {field}")
        limit = element.get("limit")
        if limit is not None and (type(limit) is not int or not 1 <= limit <= 100000):
            raise SemanticCompileError("Report limit must be an integer from 1 to 100000")
        for ref, value in _mapping(element.get("filters", {}), "Report tile filters").items():
            self.exact_filter(ref, value)
        filters = report.get("filters")
        if not isinstance(filters, list):
            raise SemanticCompileError("Report filters must be a list")
        bindings = {}
        for definition in filters:
            _keys(definition, {"name", "title", "type", "model", "explore", "field", "default_value"}, "Dashboard filter")
            name = definition.get("name")
            if not isinstance(name, str) or not name or name in bindings:
                raise SemanticCompileError("Dashboard filter names must be unique nonempty strings")
            if definition.get("model", report["model"]) != report["model"] or definition.get("explore", self.base) != self.base:
                raise SemanticCompileError("Dashboard filter model/explore binding is inconsistent")
            if definition.get("type", "field_filter") != "field_filter":
                raise SemanticCompileError("Only field_filter dashboard filters are supported")
            field = definition.get("field")
            if field not in (f"{self.base}.invoice_date", f"{self.base}.currency"):
                raise SemanticCompileError(f"Unsupported dashboard filter field: {field}")
            self.field(field)
            bindings[name] = field
        listen = _mapping(element.get("listen"), "Report listen mapping")
        if listen != bindings or len(bindings) != 2 or set(bindings.values()) != {f"{self.base}.invoice_date", f"{self.base}.currency"}:
            raise SemanticCompileError("Report must listen to the exact declared invoice_date and currency dashboard filters")

    def defaults(self):
        result = {}
        for definition in self.report["filters"]:
            value = definition.get("default_value")
            if definition["field"].endswith(".currency"):
                self.exact_filter(definition["field"], value)
                result["currency"] = value
            else:
                if not isinstance(value, str):
                    raise SemanticCompileError("Dashboard date default must be a literal calendar range")
                match = re.fullmatch(r"(\d{4}/\d{2}/\d{2}) to (\d{4}/\d{2}/\d{2})", value)
                if not match:
                    raise SemanticCompileError("Unsupported dashboard date default; expected YYYY/MM/DD to YYYY/MM/DD")
                try:
                    start = date.fromisoformat(match.group(1).replace("/", "-"))
                    end = date.fromisoformat(match.group(2).replace("/", "-")) + timedelta(days=1)
                except ValueError as error:
                    raise SemanticCompileError(f"Invalid dashboard date range: {error}") from error
                if start >= end:
                    raise SemanticCompileError("Dashboard date default is reversed")
                result.update(start_date=start.isoformat(), end_date=end.isoformat())
        return result

    def from_sql(self):
        if self.kind == "looker":
            return f'(\n{self.source_sql}\n) AS "{self.base}"'

        def physical(view):
            definition = self.views[view]
            return ".".join(f'"{definition[k]}"' for k in ("catalog", "schema", "table_name")) + f' AS "{view}"'

        relation = self.relation
        condition = self.substitute(relation["on_sql"], self.base, ("relationship",), dimensions_only=True)
        condition = _sql_expression(condition, allow_aggregates=False, aliases=self.views, physical_case=True)
        return f'{physical(self.base)}\nLEFT JOIN {physical(relation["join_to_view"])} ON {condition}'

    def compile(self, parameters, apply_dashboard_filters):
        self.validate()
        defaults = self.defaults()  # Validate defaults even when overridden.
        _keys(parameters, {"tenant", "currency", "start_date", "end_date", "group_by", "segment", "zero_net_only"}, "Query parameters")
        if parameters.get("tenant") not in ("A", "B") or type(parameters.get("tenant")) is not str:
            raise SemanticCompileError("A valid tenant attribute ('A' or 'B') is required; no security fallback exists")
        if type(apply_dashboard_filters) is not bool:
            raise SemanticCompileError("apply_dashboard_filters must be a boolean")
        values = {**defaults, **parameters}
        if not isinstance(values["currency"], str) or not re.fullmatch(r"[A-Z]{3}", values["currency"]):
            raise SemanticCompileError("Currency must be a three-letter uppercase ISO-style value")
        for name in ("start_date", "end_date"):
            value = values[name]
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise SemanticCompileError(f"{name} must be an ISO date")
            try:
                date.fromisoformat(value)
            except ValueError as error:
                raise SemanticCompileError(f"Invalid {name}: {value}") from error
        if values["start_date"] > values["end_date"]:
            raise SemanticCompileError("The half-open date interval must have start_date <= end_date; equal endpoints select no rows")
        groups = values.get("group_by", [])
        if not isinstance(groups, list) or any(group not in ("segment", "invoice_date") for group in groups) or len(groups) != len(set(groups)):
            raise SemanticCompileError("group_by must be a unique list containing segment and/or invoice_date")
        segment = values.get("segment")
        if segment is not None and (not isinstance(segment, str) or len(segment) > 200 or any(ord(c) < 32 for c in segment)):
            raise SemanticCompileError("segment must be a short exact string or null")
        if type(values.get("zero_net_only", False)) is not bool:
            raise SemanticCompileError("zero_net_only must be a boolean")
        group_fields = {"segment": f'{"customers" if self.kind == "omni" else self.base}.segment',
                        "invoice_date": f"{self.base}.invoice_date"}
        columns = [f'({self.resolve(group_fields[group])}) AS "{group}"' for group in groups]
        columns += [f'({self.resolve(f"{self.base}.{field}")}) AS "{alias}"' for field, alias in _OUTPUTS.items()]
        access = self.access[0]
        where = [f'({self.resolve(access["field"])}) = {_literal(values["tenant"])}',
                 f'({self.resolve(f"{self.base}.currency")}) = {_literal(values["currency"])}',
                 f'({self.resolve(f"{self.base}.invoice_date")}) >= CAST({_literal(values["start_date"])} AS DATE)',
                 f'({self.resolve(f"{self.base}.invoice_date")}) < CAST({_literal(values["end_date"])} AS DATE)']
        for ref, value in self.report["element"].get("filters", {}).items():
            # Diagnostic mode removes only the tile status restriction. It never
            # removes measure filters, access policies, or other fixed filters.
            if apply_dashboard_filters or ref != f"{self.base}.status":
                where.append(self.exact_filter(ref, value))
        if segment is not None:
            where.append(f'({self.resolve(group_fields["segment"])}) = {_literal(segment)}')
        if values.get("zero_net_only", False):
            where.append(f'({self.resolve(f"{self.base}.net_cents")}) = 0')
        query = "SELECT\n  " + ",\n  ".join(columns) + "\nFROM " + self.from_sql() + "\nWHERE " + "\n  AND ".join(where)
        if groups:
            query += "\nGROUP BY " + ", ".join(str(i + 1) for i in range(len(groups)))
            query += "\nORDER BY " + ", ".join(f'"{group}" ASC NULLS FIRST' for group in groups)
        if self.report["element"].get("limit") is not None:
            query += "\nLIMIT " + str(self.report["element"]["limit"])
        return query


def _looker(repo_path):
    _require_dependencies()
    repo = Path(repo_path)
    models, views, dashboards = [], [], []
    model_names, definition_paths = [], []
    for path in sorted(repo.rglob("*.lkml")):
        try:
            content = lkml.load(path.read_text())
        except Exception as error:
            raise SemanticCompileError(f"Cannot parse LookML {path}: {error}") from error
        if path.name.endswith(".model.lkml"):
            _keys(content, {"connection", "includes", "explores"}, str(path))
            models.append(content)
            model_names.append(path.name.removesuffix(".model.lkml"))
        elif path.name.endswith(".view.lkml"):
            _keys(content, {"views"}, str(path))
            views.extend(content.get("views", []))
            definition_paths.append(path)
        elif path.name == "manifest.lkml":
            _keys(content, {"project_name"}, str(path))
        else:
            raise SemanticCompileError(f"Unsupported LookML file: {path}")
    for path in sorted(repo.rglob("*.dashboard.lookml")):
        dashboards.append(_one(_load_yaml(path), str(path)))
        definition_paths.append(path)
    model = _one(models, "Looker model")
    includes = model.get("includes")
    if not isinstance(includes, list) or not includes:
        raise SemanticCompileError("Looker model must include its view and dashboard definitions")
    included = set()
    for pattern in includes:
        if not isinstance(pattern, str) or not pattern.startswith("/") or ".." in pattern.split("/"):
            raise SemanticCompileError("Only repository-root Looker include patterns are supported")
        matches = {path for path in repo.glob(pattern.lstrip("/")) if path.is_file()}
        if not matches or not matches.issubset(set(definition_paths)):
            raise SemanticCompileError(f"Unsupported or unmatched Looker include: {pattern}")
        included |= matches
    if included != set(definition_paths):
        raise SemanticCompileError("Every compiled Looker view/dashboard must be included by the model")
    view = _one(views, "Looker view")
    explore = _one(model.get("explores"), "Looker explore")
    _keys(explore, {"name", "label", "description", "access_filters"}, "Looker explore")
    _keys(view, {"name", "label", "description", "derived_table", "dimensions", "measures"}, "Looker view")
    base = _name(view.get("name"), "Looker base view")
    if explore.get("name") != base:
        raise SemanticCompileError("Looker explore must directly bind the sole source view")
    derived = view.get("derived_table")
    _keys(derived, {"sql"}, "Looker derived table")
    source_sql = derived.get("sql")
    if not isinstance(source_sql, str) or any(t in source_sql for t in ("${", "{{", "{%")):
        raise SemanticCompileError("Derived-table SQL must be literal SQL without Liquid or unresolved references")
    try:
        parsed = sqlglot.parse(source_sql, read="snowflake")
    except Exception as error:
        raise SemanticCompileError(f"Derived-table SQL is invalid: {error}") from error
    if len(parsed) != 1 or not isinstance(parsed[0], exp.Select) or parsed[0].find(exp.Into):
        raise SemanticCompileError("Derived-table SQL must be one read-only SELECT")
    dimensions, measures = _named(view.get("dimensions"), "Looker dimensions"), _named(view.get("measures"), "Looker measures")
    if set(dimensions) & set(measures):
        raise SemanticCompileError("A Looker field cannot be both dimension and measure")
    for field in dimensions.values():
        _keys(field, {"name", "sql", "type", "primary_key"} | _DECORATION, "Looker dimension")
        if field.get("type", "string") not in ("string", "number", "date"):
            raise SemanticCompileError(f"Unsupported Looker dimension type: {field.get('type')}")
    for field in measures.values():
        _keys(field, {"name", "sql", "type", "filters__all"} | _DECORATION, "Looker measure")
    dashboard = _one(dashboards, "Looker dashboard")
    _keys(dashboard, {"dashboard", "title", "layout", "preferred_viewer", "filters", "elements"}, "Looker dashboard")
    element = _one(dashboard.get("elements"), "Looker dashboard element")
    if element.get("model") != model_names[0]:
        raise SemanticCompileError("Dashboard tile model must match the parsed model filename")
    report = {"model": element.get("model"), "explore": base, "filters": dashboard.get("filters"), "element": element}
    return _Model("looker", base, {base: {"dimensions": dimensions, "measures": measures}},
                  explore.get("access_filters"), report, source_sql=source_sql)


def _omni(omni_path):
    _require_dependencies()
    root = Path(omni_path)
    allowed_files = {"invoices.view", "customers.view", "billing.topic", "relationships", "report-context.json"}
    if not root.is_dir():
        raise SemanticCompileError(f"Omni model directory is missing: {root}")
    actual_files = {p.name for p in root.iterdir() if p.is_file()}
    if actual_files != allowed_files:
        raise SemanticCompileError(f"Bounded Omni package file mismatch; missing={sorted(allowed_files-actual_files)}, unsupported={sorted(actual_files-allowed_files)}")
    views = {}
    for name in ("invoices", "customers"):
        view = _load_yaml(root / f"{name}.view")
        _keys(view, {"catalog", "schema", "table_name", "dimensions", "measures", "label", "description"}, f"Omni view {name}")
        for key in ("catalog", "schema", "table_name"):
            _name(view.get(key), f"{name}.{key}")
            if view[key] != view[key].upper():
                raise SemanticCompileError(f"{name}.{key}: physical mapping must preserve uppercase Snowflake fixture identifiers")
        dimensions = _mapping(view.get("dimensions"), f"{name} dimensions")
        measures = _mapping(view.get("measures", {}), f"{name} measures")
        if set(dimensions) & set(measures):
            raise SemanticCompileError(f"{name}: a field cannot be both dimension and measure")
        for field, definition in dimensions.items():
            _name(field, f"{name} dimension")
            _keys(definition, {"sql", "primary_key", "data_type"} | _DECORATION, f"{name}.{field}")
            if definition.get("data_type") not in (None, "string", "number", "date", "varchar", "integer"):
                raise SemanticCompileError(f"{name}.{field}: unsupported dimension data_type")
        for field, definition in measures.items():
            _name(field, f"{name} measure")
            _keys(definition, {"sql", "aggregate_type", "filters", "format"} | _DECORATION, f"{name}.{field}")
        views[name] = {**view, "dimensions": dimensions, "measures": measures}
    topic = _load_yaml(root / "billing.topic")
    _keys(topic, {"base_view", "label", "description", "joins", "access_filters"}, "Omni topic")
    if topic.get("base_view") != "invoices" or topic.get("joins") != {"customers": {}}:
        raise SemanticCompileError("Omni topic must expose the bounded invoices -> customers join")
    relation = _one(_load_yaml(root / "relationships"), "Omni relationship")
    _keys(relation, {"join_from_view", "join_to_view", "join_type", "on_sql", "relationship_type"}, "Omni relationship")
    if any(relation.get(k) != value for k, value in {"join_from_view": "invoices", "join_to_view": "customers", "join_type": "always_left", "relationship_type": "many_to_one"}.items()):
        raise SemanticCompileError("Only one invoices -> customers always_left many_to_one relationship is supported")
    if views["customers"]["dimensions"].get("customer_key", {}).get("primary_key") is not True:
        raise SemanticCompileError("customers.customer_key must declare its tested primary key")
    try:
        report = json.loads((root / "report-context.json").read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SemanticCompileError(f"Cannot read explicit Omni report context: {error}") from error
    compiled = _Model("omni", "invoices", views, topic.get("access_filters"), report, relation=relation)
    # Preserve only equality joins on declared dimensions, with a customer-key
    # equality required. Additional tenant equality remains meaningful SQL.
    on_sql = relation.get("on_sql")
    if not isinstance(on_sql, str):
        raise SemanticCompileError("Relationship on_sql must be a modeled equality expression")
    terms = re.split(r"\s+AND\s+", on_sql.strip(), flags=re.I)
    pairs = []
    for term in terms:
        match = re.fullmatch(r"\s*\$\{(invoices\.[a-z_]+)\}\s*=\s*\$\{(customers\.[a-z_]+)\}\s*", term)
        if not match:
            raise SemanticCompileError("Only conjunctions of invoices-to-customers modeled equality joins are supported")
        pairs.append(match.groups())
        for ref in match.groups():
            if compiled.field(ref)[2] != "dimension":
                raise SemanticCompileError("Relationship keys must be dimensions")
    if ("invoices.customer_key", "customers.customer_key") not in pairs or len(pairs) != len(set(pairs)):
        raise SemanticCompileError("Relationship must include the customer_key equality exactly once")
    return compiled


def compile_looker(repo_path, parameters, *, apply_dashboard_filters=True):
    """Compile actual source LookML/report definitions into Snowflake SQL."""
    return _looker(repo_path).compile(parameters, apply_dashboard_filters)


def compile_omni(omni_path, parameters, *, apply_dashboard_filters=True):
    """Compile the native YAML candidate and its explicit report context."""
    return _omni(omni_path).compile(parameters, apply_dashboard_filters)


def _describe(model):
    model.validate()
    return {"kind": model.kind, "base_view": model.base, "views": sorted(model.views),
            "dimensions": sorted(f"{v}.{f}" for v, d in model.views.items() for f in d["dimensions"]),
            "measures": sorted(f"{v}.{f}" for v, d in model.views.items() for f in d["measures"]),
            "access_filters": model.access, "report_context": model.report,
            "runtime_defaults": model.defaults(), "relationship": model.relation,
            "source_derived_sql": model.source_sql,
            "validation": "Bounded offline adapter only; native product validation was not run"}


def describe_looker(repo_path):
    return _describe(_looker(repo_path))


def describe_omni(omni_path):
    return _describe(_omni(omni_path))
