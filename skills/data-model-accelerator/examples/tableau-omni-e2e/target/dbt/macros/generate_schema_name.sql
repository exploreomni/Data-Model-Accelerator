{% macro generate_schema_name(custom_schema_name, node) -%}
  {%- if target.name == 'fixture' and target.database == 'DMA_TABLEAU' and custom_schema_name in ['SILVER', 'GOLD'] -%}
    {{ custom_schema_name }}
  {%- elif custom_schema_name is none -%}
    {{ target.schema }}
  {%- else -%}
    {{ target.schema }}_{{ custom_schema_name | trim }}
  {%- endif -%}
{%- endmacro %}
