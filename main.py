from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import cloudinary
import cloudinary.uploader
import os

app = FastAPI()

# Cloudinary-Konfiguration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

class ArtworkRequest(BaseModel):
    request_id: str
    preview_url: str
    product_type: str  # "apparel" oder "poster"

@app.post("/upscale")
def upscale_artwork(data: ArtworkRequest):
    try:
        transformations = {
            "apparel": "e_upscale,w_2500,h_2500,c_fit,q_100,f_png",
            "poster": "e_upscale,w_3000,h_3000,c_fit,q_100,f_png"
        }

        transformation = transformations.get(data.product_type, transformations["apparel"])
        folder = "portreo_artworks_production"

        result = cloudinary.uploader.upload(
            data.preview_url,
            public_id=f"{data.request_id}_production",
            folder=folder,
            transformation=transformation,
            tags=[data.product_type, "production", "upscaled"],
            upload_preset="portreo_production"
        )

        return {
            "secure_url": result.get("secure_url"),
            "width": result.get("width"),
            "height": result.get("height"),
            "bytes": result.get("bytes"),
            "format": result.get("format"),
            "asset_id": result.get("asset_id")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
