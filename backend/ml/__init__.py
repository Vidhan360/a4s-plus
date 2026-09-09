"""A4S+ machine-learning package.

Contains the synthetic dataset builder, feature pipeline, PyTorch LSTM model,
reproducible training entry point (``python -m ml.train``), evaluation and the
versioned model registry consumed by the backend's PredictionService.
"""

__all__ = ["dataset", "evaluate", "features", "model", "registry", "train"]
