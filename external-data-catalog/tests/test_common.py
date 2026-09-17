import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vec_external.common import parse_stage, stage_allowed, infer_stage_from_name


def test_stage_parse():
    assert parse_stage("E8.5") == 8.5
    assert parse_stage("E8_75TS13") == 8.75
    assert parse_stage(9.5) == 9.5


def test_task_boundaries():
    assert stage_allowed("t2-heart", 8.25)
    assert not stage_allowed("t2-heart", 8.5)
    assert stage_allowed("t2-heart", 8.75)
    assert stage_allowed("t1", 9.5)
    assert not stage_allowed("t1", 9.5001)
    assert not stage_allowed("t1", 13.5)
    assert stage_allowed("t1", 13.5001)
    assert stage_allowed("t2-embryo", 7.25)
    assert not stage_allowed("t2-embryo", 7.5)
    assert stage_allowed("t2-embryo", 8.0)


def test_filename_stage():
    assert infer_stage_from_name("E9_0_Embryo_h5ad.h5ad") == 9.0
    assert infer_stage_from_name("GSM7890128_E9.5_region_0") == 9.5
