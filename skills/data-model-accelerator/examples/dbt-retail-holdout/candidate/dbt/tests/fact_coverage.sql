select l.LINE_KEY from {{ ref('stg_order_lines') }} l
left join {{ ref('fct_order_line_fulfillment') }} f on l.LINE_KEY=f.LINE_KEY
where f.LINE_KEY is null or f.LINE_NET_CENTS <> l.LINE_NET_CENTS or f.ORDERED_QUANTITY <> l.QUANTITY
union all
select f.LINE_KEY from {{ ref('fct_order_line_fulfillment') }} f
left join {{ ref('stg_order_lines') }} l on f.LINE_KEY=l.LINE_KEY where l.LINE_KEY is null
