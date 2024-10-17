# from skimage.filters import threshold_otsu
import numpy as np


#***** V1 Code *****#
#-------------------#

# def select_regions_automatically(image_data):
#     # Calculate a threshold using Otsu's method to separate signal from background
#     threshold = threshold_otsu(image_data)

#     # Signal region: areas above the threshold
#     signal_mask = image_data > threshold
#     signal_region = image_data[signal_mask]

#     # Noise region: areas below the threshold
#     noise_mask = image_data <= threshold
#     noise_region = image_data[noise_mask]

#     return signal_region, noise_region


# def calculate_snr_auto(image_data):
#     signal_region, noise_region = select_regions_automatically(image_data)

#     signal_mean = np.mean(signal_region)
#     noise_std = np.std(noise_region)

#     snr = signal_mean / noise_std
#     return round(snr, 2)


#***** V2 Code *****#
#-------------------#

# Function to divide image into blocks for each channel
def divide_into_blocks(image, block_size):
    blocks = []
    block_means = []
    # Loop through the image in block_size increments
    for i in range(0, image.shape[0], block_size[0]):
        for j in range(0, image.shape[1], block_size[1]):
            block = image[i:i + block_size[0], j:j + block_size[1], :]
            if block.size == 0:
                continue  # Ignore any empty blocks at the edges
            blocks.append(block)
            block_means.append(np.mean(block, axis=(0, 1)))  # Mean for each color channel (R, G, B)
    return blocks, np.array(block_means)

# Function to calculate SNR for each color channel
def calculate_snr_auto(image, block_size=(120, 120)):
    # Normalize the image data for each channel (R, G, B)
    image = (image - np.min(image, axis=(0, 1))) / (np.max(image, axis=(0, 1)) - np.min(image, axis=(0, 1)))
    # Divide the image into blocks and calculate block means for each channel
    blocks, block_means = divide_into_blocks(image, block_size)
    
    # Select the background block (lowest mean value for each channel)
    background_block_idx = np.argmin(np.mean(block_means, axis=1))  # Min of the average across R, G, B channels
    background_block = blocks[background_block_idx]
    
    # Select the median block (median mean value for each channel)
    median_block_idx = np.argsort(np.mean(block_means, axis=1))[len(block_means) // 2]
    median_block = blocks[median_block_idx]
    
    # Calculate the SNR for each channel (R, G, B)
    signal_means = np.mean(median_block, axis=(0, 1))  # Mean of each channel in the median block
    background_stds = np.std(background_block, axis=(0, 1))  # Std dev of each channel in the background block
    
    # Calculate the ratio
    snr = signal_means / background_stds
    return np.sqrt(np.mean(snr ** 2))