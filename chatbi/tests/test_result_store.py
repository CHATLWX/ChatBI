from result_store import MemoryResultStore


def test_memory_result_store_round_trip():
    store = MemoryResultStore()
    reference = store.put("step_1", ["month", "profit"], [{"month": "2026-05", "profit": 920000}])
    assert reference == "memory://step_1"
    assert store.get(reference) == [{"month": "2026-05", "profit": 920000}]
