import numpy as np

from take_check.analyze import SR, waveform_peaks


def test_peaks_stay_aligned_over_long_takes():
    # einzelne Impulse nach 1 s und 240 s: müssen genau im Block k = t * per_second landen
    y = np.zeros(int(250 * SR), dtype=np.float32)
    for t in (1.0, 240.0):
        y[int(t * SR)] = 1.0
    peaks = waveform_peaks(y)
    hits = [k for k, (_, hi) in enumerate(peaks["peaks"]) if hi > 0.5]
    assert hits == [100, 24000]
    assert len(peaks["peaks"]) == 25000
