import os
import shutil
import json
import uuid
import random
import ffmpeg

# pillow (PIL fork) for image manipulation
from PIL import Image
# text-blind-watermark for text watermarking
from text_blind_watermark import TextBlindWatermark

DELIMITER = "1111111111111110" # End of watermark delimiter, 16 bits
SECRET_KEY_ENV_VAR = "WATERMARK_SECRET_KEY"
UTF_8 = "utf-8"

def _str_to_binary(text_string):
    return ''.join(format(byte, '08b') for byte in text_string.encode(UTF_8))

def _binary_to_str(binary_string):
    if len(binary_string) % 8 != 0:
        binary_string = binary_string[:len(binary_string) // 8 * 8]

    byte_array = bytearray()
    for i in range(0, len(binary_string), 8):
        byte_segment = binary_string[i:i + 8]
        if len(byte_segment) < 8:
            break
        try:
            byte_array.append(int(byte_segment, 2))
        except ValueError:
            byte_array.append(ord('?'))
    try:
        text = byte_array.decode(UTF_8, errors='replace')
    except UnicodeDecodeError:
        text = byte_array.decode('latin-1')
    return text

def _get_pixel_sequence(width, height, secret_key_string):
    seed_val = 0
    for char_code in secret_key_string.encode(UTF_8):
        seed_val = (seed_val * 31 + char_code) & 0xFFFFFFFF

    rng = random.Random(seed_val)

    locations = []
    for y_coord in range(height):
        for x_coord in range(width):
            for channel_idx in range(3):
                locations.append((y_coord, x_coord, channel_idx))
    rng.shuffle(locations)
    return locations






