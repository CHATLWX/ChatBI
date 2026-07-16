from __future__ import annotations

RULES = """
【关键业务规则】
1. 收入/销售额统一使用 sales_orders.net_amount，除非明确要求含税，禁止 gross_amount。
2. 销售成本=(material_cost+labor_cost)*quantity，禁止 standard_cost。
3. 收入、订单量、销量、成本、毛利均过滤 order_status='completed'。
4. 涉及多币种收入汇总时，按订单月份和 currency 关联 exchange_rates，并乘 rate_to_cny 折人民币。
5. “最近N个月”使用 DATE_SUB(CURDATE(), INTERVAL N MONTH) 作为起始边界；“上个月”使用上一个完整自然月的左闭右开区间。
6. selling_expense 已包含 marketing/logistics/warranty 子项，不得重复相加。
7. 订单数默认 COUNT(DISTINCT order_id)，销售数量才使用 SUM(quantity)。
8. 利润=毛利-期间费用；订单与费用必须先按月分别聚合，再按月份关联。
9. 当前数据库为 MySQL 8.0，不支持 FULL OUTER JOIN。需要完整月份集合时使用月份CTE后 LEFT JOIN，或 UNION LEFT/RIGHT JOIN。
"""

ERROR_GUARDS = """
【常见错误防护】
- 检查金额字段口径、completed 过滤和汇率关联是否齐全。
- 检查所有表名、字段名都存在于动态 Schema。
- 检查 GROUP BY 覆盖所有非聚合 SELECT 字段。
- 检查时间范围为左闭右开，不混用订单日期和费用日期。
- 禁止订单事实表与费用事实表按月份明细直接关联，防止多对多放大。
- 禁止 FULL OUTER JOIN、QUALIFY 等非 MySQL 语法。
"""

FEW_SHOT_EXAMPLES = """
示例1：查询已完成订单总数量
SELECT COUNT(DISTINCT order_id) AS order_count FROM sales_orders WHERE order_status='completed'

示例2：按客户类型统计订单数量
SELECT c.customer_type,COUNT(DISTINCT o.order_id) AS order_count
FROM sales_orders o JOIN dim_customers c ON o.customer_id=c.customer_id
WHERE o.order_status='completed' GROUP BY c.customer_type

示例3：最近三个月月度利润趋势，先分别聚合订单和费用
WITH monthly_gp AS (
  SELECT DATE_FORMAT(o.order_date,'%Y-%m') AS month,
         SUM(o.net_amount*r.rate_to_cny)-SUM((p.material_cost+p.labor_cost)*o.quantity) AS gross_profit
  FROM sales_orders o
  JOIN dim_products p ON o.product_id=p.product_id
  JOIN exchange_rates r ON o.currency=r.currency
   AND DATE_FORMAT(o.order_date,'%Y-%m')=DATE_FORMAT(r.rate_date,'%Y-%m')
  WHERE o.order_status='completed'
    AND o.order_date>=DATE_SUB(DATE_FORMAT(CURDATE(),'%Y-%m-01'),INTERVAL 3 MONTH)
    AND o.order_date<DATE_FORMAT(CURDATE(),'%Y-%m-01')
  GROUP BY DATE_FORMAT(o.order_date,'%Y-%m')
), monthly_expense AS (
  SELECT DATE_FORMAT(expense_date,'%Y-%m') AS month,
         SUM(rd_expense+selling_expense+admin_expense+finance_expense) AS total_expense
  FROM finance_expenses
  WHERE expense_date>=DATE_SUB(DATE_FORMAT(CURDATE(),'%Y-%m-01'),INTERVAL 3 MONTH)
    AND expense_date<DATE_FORMAT(CURDATE(),'%Y-%m-01')
  GROUP BY DATE_FORMAT(expense_date,'%Y-%m')
)
SELECT g.month,g.gross_profit-COALESCE(e.total_expense,0) AS profit
FROM monthly_gp g LEFT JOIN monthly_expense e ON g.month=e.month ORDER BY g.month
"""


def build_prompt(
    user_question: str,
    dynamic_schema: str,
    indicator_knowledge: str = "",
    use_few_shot: bool = True,
    use_rules: bool = True,
    use_guards: bool = True,
    execution_context: str = "",
) -> tuple[str, str]:
    system_msg = "你是企业级制造业财务 ChatBI 的 Text2SQL 专家，只生成一条可执行 MySQL 8.0 只读查询。"
    blocks = [dynamic_schema]
    if use_rules:
        blocks.append(RULES)
    if indicator_knowledge:
        blocks.append(indicator_knowledge)
    if use_few_shot:
        blocks.append("【Few-shot 示例】\n" + FEW_SHOT_EXAMPLES)
    if use_guards:
        blocks.append(ERROR_GUARDS)
    if execution_context:
        blocks.append("【前序步骤上下文】\n" + execution_context)
    blocks.append(
        f"【用户问题】\n{user_question}\n\n"
        "【输出要求】\n1. 只输出一条 SQL，不要 Markdown 和解释。\n"
        "2. 只使用动态 Schema 中存在的表字段。\n3. 生成前逐项检查业务规则与错误防护。"
    )
    return system_msg, "\n\n".join(blocks)
