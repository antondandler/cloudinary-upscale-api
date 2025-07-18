from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import cloudinary
import cloudinary.uploader
import os

app = FastAPI()

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
        transformation = {
            "apparel": "e_upscale,w_2500,h_2500,c_fit,q_100,f_png",
            "poster": "e_upscale,w_3000,h_3000,c_fit,q_100,f_png"
        }.get(data.product_type, "e_upscale,w_2500,h_2500,c_fit,q_100,f_png")

        upload_result = cloudinary.uploader.upload(
            data.preview_url,
            public_id=f"{data.request_id}_production",
            folder="portreo_artworks_production",
            transformation=transformation,
            upload_preset="portreo_production",
            tags=["upscaled", data.product_type]
        )

        return {
            "secure_url": upload_result["secure_url"],
            "width": upload_result.get("width"),
            "height": upload_result.get("height"),
            "format": upload_result.get("format"),
            "bytes": upload_result.get("bytes")
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
