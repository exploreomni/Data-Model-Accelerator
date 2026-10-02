{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if target.name == 'local' -%}{{ custom_schema_name or target.schema }}
  {%- else -%}{{ target.schema }}{% if custom_schema_name %}_{{ custom_schema_name }}{% endif %}
  {%- endif -%}
{%- endmacro %}

{% macro sql_literal(value) -%}'{{ value | replace("'", "''") }}'{%- endmacro %}

{% macro validate_report_context() -%}
  {% set tenant = var('tenant', 'A') %}
  {% if tenant not in ['A','B'] or var('persona_tenant', tenant) != tenant or var('authorized', true) is not sameas true %}
    {{ exceptions.raise_compiler_error('Report tenant/persona/authorization rejected') }}
  {% endif %}
  {% if var('status', 'completed') not in ['completed','pending','cancelled'] or var('product', 'ALL') is not string %}
    {{ exceptions.raise_compiler_error('Report status/product rejected') }}
  {% endif %}
  {% set start = var('start_date', '2026-04-01') %}
  {% set end = var('end_date', '2026-04-04') %}
  {% if start is not string or end is not string or not modules.re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', start) or not modules.re.fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', end) %}
    {{ exceptions.raise_compiler_error('ISO report dates required') }}
  {% endif %}
  {% set start_date = modules.datetime.datetime.strptime(start, '%Y-%m-%d').date() %}
  {% set end_date = modules.datetime.datetime.strptime(end, '%Y-%m-%d').date() %}
  {% if start_date > end_date %}{{ exceptions.raise_compiler_error('Reversed report interval') }}{% endif %}
{%- endmacro %}
