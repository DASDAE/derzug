"""Shared bounded-decimation helpers for large-array display and statistics."""

from __future__ import annotations

import math

import numpy as np


def strided_step(size: int, target_size: int) -> int:
    """Return the regular stride that bounds a 1D sample near ``target_size``.

    Parameters
    ----------
    size
        Number of elements in the source array.
    target_size
        Desired maximum number of sampled elements.

    Returns
    -------
    int
        A stride of at least 1 such that ``ceil(size / step) <= target_size``
        whenever ``size > target_size``, and 1 otherwise.

    Examples
    --------
    >>> strided_step(10, 100)
    1
    >>> strided_step(1_000_001, 1_000_000)
    2
    """
    if size <= target_size:
        return 1
    return max(1, math.ceil(size / target_size))


def strided_sample(values: np.ndarray, target_size: int) -> np.ndarray:
    """Return an evenly strided n-dimensional sample of at most ``target_size``.

    Every axis is sampled with the same regular stride, then the largest axis
    is halved until the element count fits the budget, so the result stays a
    cheap view of the input.

    Parameters
    ----------
    values
        Source array of any dimensionality.
    target_size
        Desired maximum number of elements in the sample.

    Returns
    -------
    numpy.ndarray
        The input itself when it already fits the budget (or is 0-d),
        otherwise a strided view with ``sample.size <= target_size``.

    Examples
    --------
    >>> strided_sample(np.arange(10), 5).size <= 5
    True
    >>> strided_sample(np.zeros((100, 100)), 1000).size <= 1000
    True
    """
    values = np.asarray(values)
    if values.size <= target_size or values.ndim == 0:
        return values
    scale = (values.size / target_size) ** (1 / values.ndim)
    step = max(1, int(np.ceil(scale)))
    slices = tuple(slice(None, None, step) for _ in values.shape)
    sampled = values[slices]
    while sampled.size > target_size:
        largest_axis = int(np.argmax(sampled.shape))
        axis_slices = [slice(None) for _ in sampled.shape]
        axis_slices[largest_axis] = slice(None, None, 2)
        sampled = sampled[tuple(axis_slices)]
    return sampled
