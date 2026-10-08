from vec_agent_bench.runner import task_ids
from vec_agent_bench.tasks import TASKS


def test_task_ids_are_unique():
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 9


def test_task_selector():
    assert task_ids("inspect_h5ad,t2_copy_last") == ["inspect_h5ad", "t2_copy_last"]
