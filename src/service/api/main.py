import fastapi
from fastapi import UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import os
import shutil
import uuid
import tempfile
from contextlib import asynccontextmanager
import logging

try:
    from watermarker_service.core.logic import (
        add_watermark_image,
        detect_watermark_image,
        add_watermark_text,
        detect_watermark_text,
        # add_watermark_video,
        # detect_watermark_video,
        SECRET_KEY_ENV_VAR,
        Image, TextBlindWatermark, ffmpeg  # To check availability
    )
except ImportError:
    import sys

    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))
    from src.service.core.watermarker import (
        add_watermark_image,
        detect_watermark_image,
        add_watermark_text,
        detect_watermark_text,
        # add_watermark_video,
        # detect_watermark_video,
        SECRET_KEY_ENV_VAR,
        Image, TextBlindWatermark, ffmpeg
    )

# --- Logging Setup ---
# Basic logging configuration for the API.
# In production, we need to use a more robust setup (e.g., structured JSON logging, log rotation).
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("watermarker_api")

WATERMARKER_MASTER_KEY = None
CORE_LIBS_AVAILABLE = True

@asynccontextmanager
async def lifespan(api: fastapi.FastAPI):
    global WATERMARKER_MASTER_KEY, CORE_LIBS_AVAILABLE

    if None in [Image, TextBlindWatermark, ffmpeg]:
        CORE_LIBS_AVAILABLE = False
        logger.critical(
            "API CRITICAL ERROR: One or more core watermarking libraries (Pillow, text-blind-watermark, ffmpeg-python) are not available. The service will not function correctly.")
    else:
        logger.info("Core watermarking libraries loaded successfully.")

    WATERMARKER_MASTER_KEY = os.environ.get(SECRET_KEY_ENV_VAR)

    yield
    # Clean up resources on shutdown (if any)
    logger.info("FastAPI application shutting down.")

app = fastapi.FastAPI(lifespan=lifespan)

# --- Helper function for file processing ---
async def _process_uploaded_file(file: UploadFile, desired_suffix: str = ".tmp"):
    """Saves an uploaded file to a temporary location and returns its path."""
    # Use the original file's suffix if possible, otherwise use the desired_suffix
    original_filename = file.filename if file.filename else "unknown_file"
    _, ext = os.path.splitext(original_filename)
    if not ext:  # If no extension in original filename
        final_suffix = desired_suffix
    else:
        final_suffix = ext

    # Create a temporary file with a meaningful suffix
    temp_file_descriptor, temp_file_path = tempfile.mkstemp(
        suffix=f"_{original_filename.replace(ext, '')}{final_suffix}")
    os.close(temp_file_descriptor)  # Close descriptor, we'll open with 'wb'

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        _cleanup_files(temp_file_path)  # Clean up if error occurs
        logger.error(f"Error saving uploaded file '{original_filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error saving uploaded file: {str(e)}")
    finally:
        await file.close()  # Ensure the UploadFile is closed
    return temp_file_path


def _cleanup_files(*paths):
    """Removes specified files if they exist. For use in background tasks."""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                logger.debug(f"Successfully removed temporary file: {path}")
            except Exception as e:
                logger.warning(f"Could not remove temporary file {path}: {e}")


# --- Middleware for Request ID and Logging (Optional but good practice) ---
@app.middleware("http")
async def request_logging_middleware(request: fastapi.Request, call_next):
    request_id = str(uuid.uuid4())
    logger.info(
        f"rid={request_id} path={request.url.path} method={request.method} client={request.client.host} - Request received")

    response = await call_next(request)

    response.headers["X-Request-ID"] = request_id
    logger.info(
        f"rid={request_id} path={request.url.path} method={request.method} status_code={response.status_code} - Request completed")
    return response


# --- Service Availability Check ---
def _check_service_ready():
    """Checks if essential configurations and libraries are available."""
    if not CORE_LIBS_AVAILABLE:
        raise HTTPException(status_code=503, detail="Service unavailable: Core libraries missing.")
    if not WATERMARKER_MASTER_KEY:
        raise HTTPException(status_code=503,
                            detail=f"Service unavailable.")


# --- Image Endpoints ---
@app.post("/watermark/image/add/", response_class=FileResponse)
async def api_add_image_watermark(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(..., description="Image file to watermark."),
        watermark_text: str = Form(None, description="Text to embed. If None, a UUID is generated.")
):
    """
    Adds a watermark to an uploaded image.
    Returns the watermarked image file.
    """
    _check_service_ready()
    request_id = str(uuid.uuid4())  # For logging this specific operation
    logger.info(f"rid={request_id} op=add_image_watermark filename='{file.filename}' - Processing started.")

    input_path = None
    output_path = None
    try:
        original_suffix = os.path.splitext(file.filename)[1] if file.filename else ".png"
        input_path = await _process_uploaded_file(file, desired_suffix=f"_input{original_suffix}")

        # Generate a temporary output path
        temp_output_fd, output_path = tempfile.mkstemp(suffix=f"_watermarked{original_suffix}")
        os.close(temp_output_fd)

        wm_text_to_embed = watermark_text if watermark_text else str(uuid.uuid4())
        logger.debug(
            f"rid={request_id} op=add_image_watermark wm_text='{wm_text_to_embed if len(wm_text_to_embed) < 50 else wm_text_to_embed[:50] + "..."}'")

        success = add_watermark_image(input_path, output_path, wm_text_to_embed, WATERMARKER_MASTER_KEY)

        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            background_tasks.add_task(_cleanup_files, input_path, output_path)
            logger.info(
                f"rid={request_id} op=add_image_watermark filename='{file.filename}' - Success, returning file.")
            return FileResponse(path=output_path, media_type=file.content_type or "image/png",
                                filename=f"watermarked_{file.filename}")
        else:
            logger.error(
                f"rid={request_id} op=add_image_watermark filename='{file.filename}' - Failed to add watermark (core logic returned false or output invalid).")
            _cleanup_files(input_path, output_path)
            raise HTTPException(status_code=500, detail="Failed to add watermark to image.")

    except HTTPException as http_exc:
        logger.warning(
            f"rid={request_id} op=add_image_watermark filename='{file.filename}' - HTTPException: {http_exc.detail}")
        _cleanup_files(input_path, output_path)
        raise http_exc
    except Exception as e:
        logger.error(f"rid={request_id} op=add_image_watermark filename='{file.filename}' - Unexpected error: {e}",
                     exc_info=True)
        _cleanup_files(input_path, output_path)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


@app.post("/watermark/image/detect/")
async def api_detect_image_watermark(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(..., description="Image file to check for watermark."),
        max_len: int = Form(200, description="Expected maximum length of the watermark in characters.")
):
    """Detects a watermark from an uploaded image."""
    _check_service_ready()
    request_id = str(uuid.uuid4())
    logger.info(f"rid={request_id} op=detect_image_watermark filename='{file.filename}' - Processing started.")
    input_path = None
    try:
        original_suffix = os.path.splitext(file.filename)[1] if file.filename else ".png"
        input_path = await _process_uploaded_file(file, desired_suffix=f"_detect{original_suffix}")

        detected_text = detect_watermark_image(input_path, WATERMARKER_MASTER_KEY, max_len)
        background_tasks.add_task(_cleanup_files, input_path)

        if detected_text:
            logger.info(f"rid={request_id} op=detect_image_watermark filename='{file.filename}' - Watermark detected.")
            return {"detected_watermark": detected_text}
        else:
            logger.info(
                f"rid={request_id} op=detect_image_watermark filename='{file.filename}' - No watermark detected.")
            return {"message": "No watermark detected or error during detection."}

    except HTTPException as http_exc:
        logger.warning(
            f"rid={request_id} op=detect_image_watermark filename='{file.filename}' - HTTPException: {http_exc.detail}")
        background_tasks.add_task(_cleanup_files, input_path)
        raise http_exc
    except Exception as e:
        logger.error(f"rid={request_id} op=detect_image_watermark filename='{file.filename}' - Unexpected error: {e}",
                     exc_info=True)
        background_tasks.add_task(_cleanup_files, input_path)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# --- Text Endpoints ---
@app.post("/watermark/text/add/", response_class=FileResponse)
async def api_add_text_watermark(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(..., description="Text file (.txt) to watermark."),
        watermark_text: str = Form(None, description="Text to embed. If None, a UUID is generated.")
):
    """Adds a watermark to an uploaded text file."""
    _check_service_ready()
    request_id = str(uuid.uuid4())
    logger.info(f"rid={request_id} op=add_text_watermark filename='{file.filename}' - Processing started.")
    input_path = None
    output_path = None
    try:
        input_path = await _process_uploaded_file(file, desired_suffix="_input.txt")

        temp_output_fd, output_path = tempfile.mkstemp(suffix="_watermarked.txt")
        os.close(temp_output_fd)

        wm_text_to_embed = watermark_text if watermark_text else str(uuid.uuid4())
        logger.debug(
            f"rid={request_id} op=add_text_watermark wm_text='{wm_text_to_embed if len(wm_text_to_embed) < 50 else wm_text_to_embed[:50] + "..."}'")

        success = add_watermark_text(input_path, output_path, wm_text_to_embed, WATERMARKER_MASTER_KEY)

        if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            background_tasks.add_task(_cleanup_files, input_path, output_path)
            logger.info(f"rid={request_id} op=add_text_watermark filename='{file.filename}' - Success, returning file.")
            return FileResponse(path=output_path, media_type="text/plain", filename=f"watermarked_{file.filename}")
        else:
            logger.error(
                f"rid={request_id} op=add_text_watermark filename='{file.filename}' - Failed to add watermark.")
            _cleanup_files(input_path, output_path)
            raise HTTPException(status_code=500, detail="Failed to add watermark to text file.")

    except HTTPException as http_exc:
        logger.warning(
            f"rid={request_id} op=add_text_watermark filename='{file.filename}' - HTTPException: {http_exc.detail}")
        _cleanup_files(input_path, output_path)
        raise http_exc
    except Exception as e:
        logger.error(f"rid={request_id} op=add_text_watermark filename='{file.filename}' - Unexpected error: {e}",
                     exc_info=True)
        _cleanup_files(input_path, output_path)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


@app.post("/watermark/text/detect/")
async def api_detect_text_watermark(
        background_tasks: BackgroundTasks,
        file: UploadFile = File(..., description="Text file (.txt) to check for watermark.")
):
    """Detects a watermark from an uploaded text file."""
    _check_service_ready()
    request_id = str(uuid.uuid4())
    logger.info(f"rid={request_id} op=detect_text_watermark filename='{file.filename}' - Processing started.")
    input_path = None
    try:
        input_path = await _process_uploaded_file(file, desired_suffix="_detect.txt")

        detected_text = detect_watermark_text(input_path, WATERMARKER_MASTER_KEY)
        background_tasks.add_task(_cleanup_files, input_path)

        if detected_text:
            logger.info(f"rid={request_id} op=detect_text_watermark filename='{file.filename}' - Watermark detected.")
            return {"detected_watermark": detected_text}
        else:
            logger.info(
                f"rid={request_id} op=detect_text_watermark filename='{file.filename}' - No watermark detected.")
            return {"message": "No watermark detected or error during detection."}

    except HTTPException as http_exc:
        logger.warning(
            f"rid={request_id} op=detect_text_watermark filename='{file.filename}' - HTTPException: {http_exc.detail}")
        background_tasks.add_task(_cleanup_files, input_path)
        raise http_exc
    except Exception as e:
        logger.error(f"rid={request_id} op=detect_text_watermark filename='{file.filename}' - Unexpected error: {e}",
                     exc_info=True)
        background_tasks.add_task(_cleanup_files, input_path)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# --- Root Endpoint for Health Check/Info ---
@app.get("/", summary="API Root/Health Check")
async def root():
    """Provides a basic health check / welcome message for the API."""
    if not CORE_LIBS_AVAILABLE or not WATERMARKER_MASTER_KEY:
        status = "degraded (check logs for missing libraries or configs)"
    else:
        status = "running"
    return {"message": f"Digital Watermarking API is {status}."}