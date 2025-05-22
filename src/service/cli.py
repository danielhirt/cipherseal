import argparse
import os
import sys
import uuid

try:
    from src.service.core.watermarker import (
        generate_watermark,
        add_watermark_image,
        detect_watermark_image,
        add_watermark_text,
        detect_watermark_text,
        # add_watermark_video,
        # detect_watermark_video,
        SECRET_KEY_ENV_VAR,
        Image, TextBlindWatermark, ffmpeg
    )
except ImportError:
    # Fallback for direct execution if src is not in path, though -m is preferred
    print("Attempting fallback import for core - consider running with 'python -m src.watermarker_service.cli'")
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
    from src.service.core.watermarker import (
        generate_watermark,
        add_watermark_image,
        detect_watermark_image,
        add_watermark_text,
        detect_watermark_text,
        # add_watermark_video,
        # detect_watermark_video,
        SECRET_KEY_ENV_VAR,
        Image, TextBlindWatermark, ffmpeg
    )

def main_cli():
    """Main function to parse arguments and dispatch actions for the CLI."""
    if None in [Image, TextBlindWatermark, ffmpeg]:
        print(
            "CLI Error: One or more critical libraries (Pillow, text-blind-watermark, ffmpeg-python) are missing or failed to import from core. Please ensure they are installed and accessible.")
        return 1

    secret_key = os.environ.get(SECRET_KEY_ENV_VAR)
    if not secret_key:
        return 1

    parser = argparse.ArgumentParser(
        description="CipherSeal CLI.\nReads the master secret key from the WATERMARKER_SECRET_KEY environment variable.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("action", choices=["add", "detect"], help="Action to perform: add or detect watermark.")
    parser.add_argument("media_type", choices=["image", "text", "video"], help="Type of media to process.")
    parser.add_argument("input_path", help="Path to the input media file.")
    parser.add_argument("-o", "--output_path",
                        help="Path to save the watermarked media file (required for 'add' action).")

    parser.add_argument(
        "-w", "--watermark",
        help="The watermark text to embed.\nIf not provided for 'add' action, a unique UUID will be generated and used automatically."
    )

    parser.add_argument("--frame_interval", type=int, default=30,
                        help="For video processing: watermark or check every Nth frame (default: 30).")
    parser.add_argument("--max_len", type=int, default=200,
                        help="For image/video detection: expected max length of watermark in characters (default: 200).\nThis helps limit the search space during detection.")
    parser.add_argument("--video_frames_to_check", type=int, default=5,
                        help="For video detection: how many potentially watermarked frames to extract and check (default: 5).")

    args = parser.parse_args()

    watermark_to_embed = args.watermark
    if args.action == "add":
        if not args.output_path:
            parser.error("Output path (-o/--output_path) is required for 'add' action.")
        if not args.watermark:  # If no watermark explicitly provided by user
            watermark_to_embed = generate_watermark()
            print(
                f"CLI Info: No explicit watermark text provided, generating unique watermark.")

    if args.action == "add":
        success = False
        print(f"CLI Info: Attempting to 'add' watermark to {args.media_type} '{args.input_path}'...")
        if args.media_type == "image":
            success = add_watermark_image(args.input_path, args.output_path, watermark_to_embed, secret_key)
        elif args.media_type == "text":
            success = add_watermark_text(args.input_path, args.output_path, watermark_to_embed, secret_key)
        # elif args.media_type == "video":
        #     success = add_watermark_video(args.input_path, args.output_path, watermark_to_embed, secret_key,
        #                                   args.frame_interval)

        if success:
            print(f"CLI Success: Watermark added successfully to '{args.output_path}'.")
        else:
            print(
                f"CLI Error: Failed to add watermark for '{args.input_path}'. Check previous error messages from core logic.")
            return 1

    elif args.action == "detect":
        detected_wm = None
        print(f"CLI Info: Attempting to 'detect' watermark in {args.media_type} '{args.input_path}'...")
        if args.media_type == "image":
            detected_wm = detect_watermark_image(args.input_path, secret_key, args.max_len)
        elif args.media_type == "text":
            detected_wm = detect_watermark_text(args.input_path, secret_key)
        # elif args.media_type == "video":
        #     detected_wm = detect_watermark_video(args.input_path, secret_key, args.max_len, args.frame_interval,
        #                                          args.video_frames_to_check)

        if detected_wm:
            print(f"CLI Success: Detected watermark: '{detected_wm}'")
        else:
            print("CLI Info: No watermark detected or an error occurred during detection.")
            return 1
    return 0

if __name__ == "__main__":
    exit_code = main_cli()
    sys.exit(exit_code)
