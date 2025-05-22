import os
import shutil
import json
import uuid
import random
import traceback

# Pillow (PIL Fork) for image manipulation
try:
    from PIL import Image
except ImportError:
    Image = None

# text-blind-watermark for text watermarking
try:
    from text_blind_watermark import TextBlindWatermark
except ImportError:
    TextBlindWatermark = None

try:
    import ffmpeg
except ImportError:
    ffmpeg = None

# --- Constants ---
DELIMITER = "1111111111111110" # End of watermark delimiter, 16 bits
SECRET_KEY_ENV_VAR = "WATERMARKER_SECRET_KEY"

# --- Utility Functions ---
def generate_watermark():
    return str(uuid.uuid4())


def _str_to_binary(text_string):
    """Convert a string to its binary representation (UTF-8 encoded)."""
    return ''.join(format(byte, '08b') for byte in text_string.encode('utf-8'))


def _binary_to_str(binary_string):
    """Convert a binary string back to a string (UTF-8 decoded)."""
    text = ""
    original_binary_len = len(binary_string)

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
        text = byte_array.decode('utf-8', errors='replace')
        if '' in text:
            pass
    except UnicodeDecodeError as e:
        text = byte_array.decode('latin-1')
    return text


def _get_pixel_sequence(width, height, secret_key_string):
    """
    Generates a pseudo-random, deterministic sequence of bit locations
    (pixel_x, pixel_y, channel_index) based on a secret key string.
    """
    seed_val = 0
    for char_code in secret_key_string.encode('utf-8'):
        seed_val = (seed_val * 31 + char_code) & 0xFFFFFFFF

    rng = random.Random(seed_val)

    # Create a list of (x, y) coordinates first
    pixel_coords = []
    for y_coord in range(height):
        for x_coord in range(width):
            pixel_coords.append((x_coord, y_coord))
    rng.shuffle(pixel_coords)  # Shuffle the (x,y) coordinates

    # Now generate the full sequence including channel, iterating through shuffled pixels
    # This avoids creating an intermediate list 3x the number of pixels if memory is a concern
    # for very large images, though for LSB embedding we need to visit each bit location.
    # The previous approach of shuffling all (x,y,channel_idx) is fine and likely clearer.
    # Let's stick to the previous full shuffle for correctness of keyed LSB.
    locations = []
    for y_coord in range(height):
        for x_coord in range(width):
            for channel_idx in range(3):  # R=0, G=1, B=2
                locations.append((x_coord, y_coord, channel_idx))
    rng.shuffle(locations)
    return locations


# --- Image Watermarking Functions (Keyed LSB) - OPTIMIZED ---

def add_watermark_image(input_image_path, output_image_path, watermark_text, secret_key):
    """
    Embeds a watermark into an image using LSB steganography with a keyed pixel sequence.
    Optimized to use Pillow's PixelAccess object for faster pixel manipulation.
    """
    if not Image:
        return False

    try:
        img = Image.open(input_image_path).convert("RGB")  # Ensure 3 channels (RGB)
        pixels = img.load()  # Get PixelAccess object for direct manipulation
        width, height = img.size

        binary_watermark = _str_to_binary(watermark_text) + DELIMITER
        watermark_len_bits = len(binary_watermark)

        total_bits_available = width * height * 3
        if watermark_len_bits > total_bits_available:
            return False

        pixel_sequence = _get_pixel_sequence(width, height, secret_key)

        if watermark_len_bits > len(pixel_sequence):  # Should be same as total_bits_available
            return False

        embedded_bits_count = 0
        for x_coord, y_coord, channel_idx in pixel_sequence:
            if embedded_bits_count < watermark_len_bits:
                r, g, b = pixels[x_coord, y_coord]  # Read current pixel values

                bit_to_embed = int(binary_watermark[embedded_bits_count])

                if channel_idx == 0:  # Red channel
                    r = (r & ~1) | bit_to_embed
                elif channel_idx == 1:  # Green channel
                    g = (g & ~1) | bit_to_embed
                else:  # Blue channel (channel_idx == 2)
                    b = (b & ~1) | bit_to_embed

                pixels[x_coord, y_coord] = (r, g, b)  # Write modified pixel values back
                embedded_bits_count += 1
            else:
                break  # All watermark bits embedded

        if embedded_bits_count < watermark_len_bits:
            return False  # Should not happen if checks are correct

        output_format = os.path.splitext(output_image_path)[1].lower()
        if output_format in ['.jpg', '.jpeg']:
            print(
                f"WARNING (core.logic): Saving watermarked image to lossy format '{output_format}'. LSB data is unlikely to be reliably retrieved.")

        img.save(output_image_path)
        return True
    except FileNotFoundError:
        print(f"Error: Input text file not found at {input_image_path}")
        return False
    except Exception as e:
        print(f"Error during image watermarking: {e}")
        return False


def detect_watermark_image(input_image_path, secret_key, expected_max_len_chars=200):
    """
    Detects and extracts a watermark from an image using LSB steganography with a keyed pixel sequence.
    Optimized to use Pillow's PixelAccess object.
    """
    if not Image:
        return None

    try:
        img = Image.open(input_image_path).convert("RGB")
        pixels = img.load()
        width, height = img.size

        pixel_sequence = _get_pixel_sequence(width, height, secret_key)
        binary_watermark_extracted = ""
        max_bits_to_extract = (expected_max_len_chars * 8 * 2) + len(DELIMITER)

        extracted_bits_count = 0
        for x_coord, y_coord, channel_idx in pixel_sequence:
            if extracted_bits_count < max_bits_to_extract:
                r, g, b = pixels[x_coord, y_coord]

                if channel_idx == 0:  # Red channel
                    extracted_bit = str(r & 1)
                elif channel_idx == 1:  # Green channel
                    extracted_bit = str(g & 1)
                else:  # Blue channel
                    extracted_bit = str(b & 1)

                binary_watermark_extracted += extracted_bit
                extracted_bits_count += 1

                if binary_watermark_extracted.endswith(DELIMITER):
                    watermark_payload_binary = binary_watermark_extracted[:-len(DELIMITER)]
                    return _binary_to_str(watermark_payload_binary)
            else:
                break
        return None
    except FileNotFoundError:
        print(f"Error: Input text file not found at {input_image_path}")
        return None
    except Exception as e:
        print(f"Error during image watermarking detection: {e}")
        return None

# --- Text Watermarking Functions ---
def add_watermark_text(input_text_path, output_text_path, watermark_text, secret_key_for_text):
    """
    Embeds a watermark into a text file using the text-blind-watermark library.
    """
    if not TextBlindWatermark:
        return False
    try:
        with open(input_text_path, 'r', encoding='utf-8') as f:
            original_text = f.read()
        tbw = TextBlindWatermark(pwd=secret_key_for_text.encode('utf-8'))
        text_with_wm = tbw.add_wm_rnd(text=original_text, wm=watermark_text.encode('utf-8'))
        with open(output_text_path, 'w', encoding='utf-8') as f:
            f.write(text_with_wm)
        return True
    except FileNotFoundError:
        print(f"Error: Input text file not found at {input_text_path}")
        return False
    except Exception as e:
        print(f"Error during text watermarking: {e}")
        return False

def detect_watermark_text(input_text_path, secret_key_for_text):
    """
    Detects a watermark from a text file using the text-blind-watermark library.
    """
    if not TextBlindWatermark:
        return None
    try:
        with open(input_text_path, 'r', encoding='utf-8') as f:
            watermarked_text = f.read()
        tbw = TextBlindWatermark(pwd=secret_key_for_text.encode('utf-8'))
        extracted_watermark = tbw.extract(watermarked_text)
        return extracted_watermark
    except FileNotFoundError:
        print(f"Error: Input text file not found at {input_text_path}")
        return False
    except Exception as e:
        print(f"Error during text watermarking detection: {e}")
        return False