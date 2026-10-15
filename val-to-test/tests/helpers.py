import numpy as np

from stages import Stage


def make_stage(name, t, X, coords=None, ct=None, has_coords=True):
    X = np.asarray(X, dtype=np.float32)
    n, g = X.shape
    coords = np.zeros((n, 3)) if coords is None else np.asarray(coords)
    ct = np.array(["a"] * n) if ct is None else np.asarray(ct)
    return Stage(name=name, time=float(t), X=X, coords=np.asarray(coords, dtype=np.float32), ct=ct,
                 genes=np.array([f"g{i}" for i in range(g)]), has_coords=has_coords)
