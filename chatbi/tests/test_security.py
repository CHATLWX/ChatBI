import pytest

from models import UserContext
from security import QuerySecurityManager, SecurityError


def test_rejects_write_statement():
    with pytest.raises(SecurityError):
        QuerySecurityManager().secure_sql("DELETE FROM sales_orders")


def test_rejects_multiple_statements():
    with pytest.raises(SecurityError):
        QuerySecurityManager().secure_sql("SELECT 1; SELECT 2")


def test_injects_sales_region_scope_before_group_by():
    sql = "SELECT c.region, COUNT(*) FROM sales_orders o JOIN dim_customers c ON o.customer_id=c.customer_id GROUP BY c.region"
    secured = QuerySecurityManager().secure_sql(sql, UserContext(user_id="u1", role="sales", region="欧洲"))
    assert "WHERE c.region = '欧洲' GROUP BY" in secured
