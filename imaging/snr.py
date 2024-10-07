from skimage.filters import threshold_otsu
import numpy as np


def select_regions_automatically(image_data):
    # Calculate a threshold using Otsu's method to separate signal from background
    threshold = threshold_otsu(image_data)

    # Signal region: areas above the threshold
    signal_mask = image_data > threshold
    signal_region = image_data[signal_mask]

    # Noise region: areas below the threshold
    noise_mask = image_data <= threshold
    noise_region = image_data[noise_mask]

    return signal_region, noise_region


def calculate_snr_auto(image_data):
    signal_region, noise_region = select_regions_automatically(image_data)

    signal_mean = np.mean(signal_region)
    noise_std = np.std(noise_region)

    snr = signal_mean / noise_std
    return round(snr, 2)
