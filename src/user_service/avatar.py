from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
from PIL import Image
import io

router = APIRouter()

AVATAR_DIR = Path("avatars")
AVATAR_DIR.mkdir(exist_ok=True)

MAX_AVATAR_SIZE = (256, 256)


@router.post("/users/{user_id}/avatar")
async def upload_avatar(user_id: int, file: UploadFile = File(...)):
    """Upload and crop a user's avatar image."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        image = Image.open(io.BytesIO(await file.read()))
        width, height = image.size
        min_dim = min(width, height)

        left = (width - min_dim) / 2
        top = (height - min_dim) / 2
        right = (width + min_dim) / 2
        bottom = (height + min_dim) / 2
        image = image.crop((left, top, right, bottom))

        image.thumbnail(MAX_AVATAR_SIZE)
        avatar_path = AVATAR_DIR / f"{user_id}.jpg"
        image.save(avatar_path, "JPEG", quality=85)

        return {"message": "Avatar uploaded successfully"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image processing failed: {e}")


@router.get("/users/{user_id}/avatar")
async def get_avatar(user_id: int):
    """Return the user's avatar image."""
    avatar_path = AVATAR_DIR / f"{user_id}.jpg"
    if not avatar_path.exists():
        raise HTTPException(status_code=404, detail="Avatar not found")
    return FileResponse(avatar_path)
