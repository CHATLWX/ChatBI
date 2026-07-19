from __future__ import annotations


TABLE_METADATA = {
    "dim_customers": {
        "domain": "客户维度",
        "description": "客户维度表，存储客户名称、客户类型、所属行业、国家和大区。用于客户贡献、客户类型、国家与区域分析。",
        "key_fields": "customer_id, customer_name, customer_type, industry, country, region",
    },
    "dim_products": {
        "domain": "产品维度",
        "description": "产品维度表，存储产品线、产品类别、技术路线及标准成本、材料成本、人工成本。用于产品线、技术路线和销售成本分析。",
        "key_fields": "product_id, product_name, product_line, category, tech_route, material_cost, labor_cost",
    },
    "sales_orders": {
        "domain": "销售事实",
        "description": "销售订单事实表，记录客户、产品、区域、订单日期、状态、销售数量、折扣、含税金额、不含税收入和币种。收入必须使用 net_amount，销售指标仅统计 completed。",
        "key_fields": "order_id, customer_id, product_id, order_date, order_status, quantity, gross_amount, net_amount, currency",
    },
    "exchange_rates": {
        "domain": "汇率参考",
        "description": "汇率表，记录各日期各币种兑人民币汇率。当前数据为月度汇率，按订单月份和 currency 关联，用于人民币口径汇总。",
        "key_fields": "rate_date, currency, rate_to_cny",
    },
    "finance_expenses": {
        "domain": "财务事实",
        "description": "期间费用事实表，按月和部门记录研发、销售、管理、财务费用，以及市场、物流、质保子项。selling_expense 已包含销售费用子项，不得重复相加。",
        "key_fields": "expense_id, expense_date, department, rd_expense, selling_expense, admin_expense, finance_expense",
    },
    "hr_attendance_records": {
        "domain": "人力资源",
        "description": "员工每日考勤记录，包含人员、出勤日期、迟到、请假和缺勤状态，用于人力资源出勤管理。",
        "key_fields": "employee_id, attendance_date, status",
    },
    "iot_device_alerts": {
        "domain": "设备运维",
        "description": "工厂物联网设备告警记录，包含设备、告警时间、严重级别和处理状态，用于设备运维。",
        "key_fields": "device_id, alert_time, severity",
    },
    "legal_contract_archive": {
        "domain": "法务档案",
        "description": "法务合同档案元数据，包含合同编号、签署日期、归档位置和档案状态，用于法务文档管理。",
        "key_fields": "contract_id, signed_date, archive_status",
    },
    "warehouse_temperature_logs": {
        "domain": "仓储监控",
        "description": "仓库温度传感器日志，包含传感器、采集时间、温度值和异常标记，用于仓储环境监控。",
        "key_fields": "sensor_id, recorded_at, temperature",
    },
}


FIELD_METADATA = {
    "dim_customers.customer_id": "客户唯一标识，用于关联 sales_orders.customer_id。",
    "dim_customers.customer_name": "客户名称，可能涉及敏感客户信息。",
    "dim_customers.customer_type": "客户类型：OEM整车厂、储能集成商、电网集团、工商业用户等。",
    "dim_customers.industry": "客户所属行业：交通、能源、工业、特种交通。",
    "dim_customers.country": "具体国家，如 Germany；不是大区。",
    "dim_customers.region": "客户所属大区，如欧洲、北美、中国，用于市场和区域分析。",
    "dim_products.product_id": "产品唯一标识，用于关联 sales_orders.product_id。",
    "dim_products.product_name": "产品名称。",
    "dim_products.product_line": "产品线或业务线，用于产品线收入、成本和毛利分析。",
    "dim_products.category": "产品细分类别。",
    "dim_products.tech_route": "技术路线：三元锂、磷酸铁锂、钠离子、固态电池。",
    "dim_products.standard_cost": "标准或预算成本，不代表实际销售成本；实际成本不得使用此字段。",
    "dim_products.material_cost": "单位材料实际成本，销售成本计算必须使用。",
    "dim_products.labor_cost": "单位人工实际成本，销售成本计算必须使用。",
    "sales_orders.order_id": "订单唯一标识；订单数默认 COUNT(DISTINCT order_id)。",
    "sales_orders.order_no": "业务订单编号。",
    "sales_orders.customer_id": "客户外键。",
    "sales_orders.product_id": "产品外键。",
    "sales_orders.region": "订单销售区域；客户市场分析优先使用 dim_customers.region。",
    "sales_orders.order_date": "订单日期，销售指标时间过滤字段。",
    "sales_orders.order_status": "订单状态 completed/cancelled/pending；销售指标必须过滤 completed。",
    "sales_orders.quantity": "销售数量，单位 MWh 或套数；不代表订单笔数。",
    "sales_orders.unit_price": "不含税单价。",
    "sales_orders.discount_amount": "订单折扣金额。",
    "sales_orders.gross_amount": "含税总额；除非用户明确要求含税，否则销售额不得使用。",
    "sales_orders.net_amount": "不含税收入，财务口径的销售额、收入和营收必须使用。",
    "sales_orders.currency": "订单结算币种，多币种汇总必须关联汇率。",
    "exchange_rates.rate_date": "汇率日期，当前数据按月存储。",
    "exchange_rates.currency": "币种，与订单 currency 关联。",
    "exchange_rates.rate_to_cny": "兑人民币汇率，人民币收入为 net_amount*rate_to_cny。",
    "finance_expenses.expense_id": "费用记录唯一标识。",
    "finance_expenses.expense_date": "费用归属日期，期间费用时间过滤字段。",
    "finance_expenses.department": "费用归属部门。",
    "finance_expenses.rd_expense": "研发费用。",
    "finance_expenses.selling_expense": "销售费用总项，包含市场、物流和质保子项。",
    "finance_expenses.admin_expense": "管理费用。",
    "finance_expenses.finance_expense": "财务费用。",
    "finance_expenses.marketing_expense": "市场费用，属于销售费用子项。",
    "finance_expenses.logistics_expense": "物流费用，属于销售费用子项。",
    "finance_expenses.warranty_expense": "质保费用，属于销售费用子项。",
}


FIELD_RULES = [
    {
        "type": "whitelist",
        "trigger_keywords": ["收入", "销售额", "营业收入", "营收"],
        "force_include": ["sales_orders.net_amount", "sales_orders.order_date", "sales_orders.currency", "exchange_rates.rate_date", "exchange_rates.currency", "exchange_rates.rate_to_cny"],
        "reason": "收入口径必须使用不含税收入 net_amount",
    },
    {
        "type": "whitelist",
        "trigger_keywords": ["毛利", "毛利率"],
        "force_include": ["sales_orders.net_amount", "sales_orders.order_date", "sales_orders.order_status", "sales_orders.currency", "exchange_rates.rate_date", "exchange_rates.currency", "exchange_rates.rate_to_cny"],
        "reason": "毛利类指标需要收入、汇率和订单状态字段，不涉及期间费用",
    },
    {
        "type": "whitelist",
        "trigger_keywords": ["利润", "利润率"],
        "force_include": ["sales_orders.net_amount", "sales_orders.order_date", "sales_orders.order_status", "sales_orders.currency", "exchange_rates.rate_date", "exchange_rates.currency", "exchange_rates.rate_to_cny", "finance_expenses.expense_date"],
        "reason": "利润类指标需要收入、汇率、状态与费用时间字段",
    },
    {
        "type": "blacklist",
        "trigger_keywords": ["收入", "销售额", "营业收入", "营收"],
        "force_exclude": ["sales_orders.gross_amount"],
        "reason": "除非明确要求含税，否则排除 gross_amount",
    },
    {
        "type": "whitelist",
        "trigger_keywords": ["销售成本", "成本", "毛利", "利润"],
        "force_include": ["dim_products.material_cost", "dim_products.labor_cost", "sales_orders.quantity"],
        "reason": "实际销售成本使用材料成本+人工成本乘数量",
    },
    {
        "type": "whitelist",
        "trigger_keywords": ["订单数", "订单数量", "订单笔数"],
        "force_include": ["sales_orders.order_id"],
        "reason": "订单数量默认指订单笔数",
    },
]


JOIN_RELATIONS = [
    ("sales_orders", "customer_id", "dim_customers", "customer_id"),
    ("sales_orders", "product_id", "dim_products", "product_id"),
    ("sales_orders", "currency", "exchange_rates", "currency"),
]
