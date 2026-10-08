import importlib.util
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "processors" / "process_gse247450.py"
spec = importlib.util.spec_from_file_location("gse", P)
gse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gse)

def test_sample_key():
    assert gse._sample_key(Path("GSM7890128_E9.5_region_0_cell_by_gene.csv.gz")) == "GSM7890128_E9.5_region_0"
    assert gse._sample_key(Path("GSM7890128_E9.5_region_0_cell_metadata.csv.gz")) == "GSM7890128_E9.5_region_0"
