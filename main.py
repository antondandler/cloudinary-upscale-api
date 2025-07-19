from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import cloudinary
import cloudinary.uploader
import os

app = FastAPI()

# CORS erlauben (falls nötig)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cloudinary Konfiguration (aus ENV)
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# Eingabemodell
class UpscaleRequest(BaseModel):
    request_id: str
    preview_url: str
    product_type: str

@app.post("/upscale")
async def upscale_artwork(data: UpscaleRequest):
    try:
        # Nur bestimmte Produkttypen upscalen
        if data.product_type.lower() not in ["poster", "canvas", "framed_poster"]:
            raise HTTPException(status_code=400, detail="Product type does not require upscaling")

        # Datei herunterladen
        import requests
        from tempfile import NamedTemporaryFile

        response = requests.get(data.preview_url)
        if response.status_code != 200:
            raise HTTPException(status_code=422, detail="Failed to download preview image")

        with NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        # Upload mit Transformation (Upscaling)
        result = cloudinary.uploader.upload(
            tmp_path,
            public_id=f"portreo_artworks/{data.request_id}",
            overwrite=True,
            transformation=[
    {
        "width": 3000,
        "height": 3000,
        "crop": "fit",
        "quality": "auto",
        "fetch_format": "png"
    }
]
        )

        # Nur relevante Felder zurückgeben
        return {
            "secure_url": result["secure_url"],
            "width": result["width"],
            "height": result["height"],
            "bytes": result["bytes"],
            "format": result["format"],
            "public_id": result["public_id"]
        }

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
