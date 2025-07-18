#!/usr/bin/env python3
"""
Cloudinary Upscaling API für portreo.shop
==========================================

Diese API verwaltet das Upscaling von Kunstwerken für die Gelato-Produktion.
Funktionen:
- Automatisches Upscaling basierend auf Produkttyp
- Qualitätskontrolle und Validierung
- Batch-Processing für große Bestellungen
- Monitoring und Fehlerbehandlung
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import cloudinary
import cloudinary.uploader
import cloudinary.api
from cloudinary.utils import cloudinary_url
import requests
from supabase import create_client, Client
from flask import Flask, request, jsonify
from flask_cors import CORS

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Konfiguration
class Config:
    CLOUDINARY_CLOUD_NAME = os.getenv('CLOUDINARY_CLOUD_NAME')
    CLOUDINARY_API_KEY = os.getenv('CLOUDINARY_API_KEY')
    CLOUDINARY_API_SECRET = os.getenv('CLOUDINARY_API_SECRET')
    
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    
    GELATO_API_KEY = os.getenv('GELATO_API_KEY')
    GELATO_WEBHOOK_URL = os.getenv('GELATO_WEBHOOK_URL')
    
    # Qualitätseinstellungen
    MAX_FILE_SIZE_MB = 50
    MIN_DIMENSION_POSTER = 2000
    MIN_DIMENSION_APPAREL = 1500
    UPSCALE_PIXEL_LIMIT = 4.2 * 1000000  # 4.2 Megapixel

# Enums
class ProductType(Enum):
    POSTER = "poster"
    APPAREL = "apparel"
    CANVAS = "canvas"

class UpscalingStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    QUALITY_ISSUES = "quality_issues"

# Datenklassen
@dataclass
class UpscalingStrategy:
    can_upscale: bool
    product_type: ProductType
    current_pixels: int
    recommended_transformation: str
    target_dimensions: Dict[str, int]
    quality_level: str
    estimated_processing_time: int  # Sekunden

@dataclass
class ValidationResult:
    is_valid: bool
    issues: List[str]
    metrics: Dict[str, any]
    quality_score: float

@dataclass
class ArtworkRequest:
    request_id: str
    shopify_order_id: str
    product_title: str
    variant_title: str
    artwork_url: str
    pet_name: str
    status: str

# Cloudinary Upscaling Service
class CloudinaryUpscalingService:
    def __init__(self):
        # Cloudinary konfigurieren
        cloudinary.config(
            cloud_name=Config.CLOUDINARY_CLOUD_NAME,
            api_key=Config.CLOUDINARY_API_KEY,
            api_secret=Config.CLOUDINARY_API_SECRET
        )
        
        # Supabase Client
        self.supabase: Client = create_client(
            Config.SUPABASE_URL,
            Config.SUPABASE_KEY
        )
    
    def determine_product_type(self, product_title: str, variant_title: str) -> ProductType:
        """Bestimmt den Produkttyp basierend auf Titel und Variante."""
        full_title = f"{product_title} {variant_title or ''}".lower()
        
        apparel_keywords = ['hoodie', 't-shirt', 'tshirt', 'sweatshirt', 'shirt', 'apparel']
        canvas_keywords = ['canvas', 'leinwand']
        
        if any(keyword in full_title for keyword in apparel_keywords):
            return ProductType.APPAREL
        elif any(keyword in full_title for keyword in canvas_keywords):
            return ProductType.CANVAS
        else:
            return ProductType.POSTER
    
    def get_image_info(self, cloudinary_public_id: str) -> Dict:
        """Holt Bildinformationen von Cloudinary."""
        try:
            result = cloudinary.api.resource(cloudinary_public_id)
            return {
                'width': result.get('width', 1024),
                'height': result.get('height', 1024),
                'format': result.get('format', 'png'),
                'bytes': result.get('bytes', 0),
                'public_id': result.get('public_id'),
                'secure_url': result.get('secure_url')
            }
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Bildinformationen: {e}")
            return {
                'width': 1024,
                'height': 1024,
                'format': 'png',
                'bytes': 0
            }
    
    def create_upscaling_strategy(self, artwork: ArtworkRequest) -> UpscalingStrategy:
        """Erstellt eine Upscaling-Strategie basierend auf Artwork-Daten."""
        # Produkttyp bestimmen
        product_type = self.determine_product_type(artwork.product_title, artwork.variant_title)
        
        # Bildinformationen abrufen
        public_id = artwork.request_id  # Annahme: public_id = request_id
        image_info = self.get_image_info(public_id)
        
        current_pixels = image_info['width'] * image_info['height']
        can_upscale = current_pixels < Config.UPSCALE_PIXEL_LIMIT
        
        # Transformations-Parameter basierend auf Produkttyp
        transformations = {
            ProductType.APPAREL: {
                'upscale': 'e_upscale,w_2500,h_2500,c_fit,q_100,f_png',
                'enhance': 'e_enhance,w_2500,h_2500,c_fit,q_100,f_png',
                'dimensions': {'width': 2500, 'height': 2500}
            },
            ProductType.POSTER: {
                'upscale': 'e_upscale,w_3000,h_3000,c_fit,q_100,f_png',
                'enhance': 'e_enhance,w_3000,h_3000,c_fit,q_100,f_png',
                'dimensions': {'width': 3000, 'height': 3000}
            },
            ProductType.CANVAS: {
                'upscale': 'e_upscale,w_4000,h_4000,c_fit,q_100,f_png',
                'enhance': 'e_enhance,w_4000,h_4000,c_fit,q_100,f_png',
                'dimensions': {'width': 4000, 'height': 4000}
            }
        }
        
        config = transformations[product_type]
        
        if can_upscale:
            transformation = config['upscale']
            quality_level = 'upscaled_4x'
            processing_time = 60  # Sekunden
        else:
            transformation = config['enhance']
            quality_level = 'enhanced'
            processing_time = 30  # Sekunden
        
        return UpscalingStrategy(
            can_upscale=can_upscale,
            product_type=product_type,
            current_pixels=current_pixels,
            recommended_transformation=transformation,
            target_dimensions=config['dimensions'],
            quality_level=quality_level,
            estimated_processing_time=processing_time
        )
    
    def create_production_image(self, artwork: ArtworkRequest, strategy: UpscalingStrategy) -> Dict:
        """Erstellt das hochqualitative Produktionsbild."""
        try:
            # Production Public ID
            production_public_id = f"{artwork.request_id}_production"
            
            # Upload mit Transformation
            result = cloudinary.uploader.upload(
                artwork.artwork_url,
                public_id=production_public_id,
                folder="portreo_artworks_production",
                transformation=strategy.recommended_transformation,
                tags=[
                    "production",
                    strategy.quality_level,
                    strategy.product_type.value
                ],
                overwrite=True,
                resource_type="image"
            )
            
            logger.info(f"Production image created: {result['secure_url']}")
            return result
            
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Produktionsbildes: {e}")
            raise
    
    def validate_production_image(self, production_result: Dict, strategy: UpscalingStrategy) -> ValidationResult:
        """Validiert die Qualität des Produktionsbildes."""
        issues = []
        
        # Dimensionen prüfen
        width = production_result.get('width', 0)
        height = production_result.get('height', 0)
        
        min_dimension = (Config.MIN_DIMENSION_POSTER if strategy.product_type == ProductType.POSTER 
                        else Config.MIN_DIMENSION_APPAREL)
        
        if width < min_dimension or height < min_dimension:
            issues.append(f"Auflösung zu niedrig: {width}x{height} (min: {min_dimension})")
        
        # Dateigröße prüfen
        file_size_mb = production_result.get('bytes', 0) / (1024 * 1024)
        if file_size_mb > Config.MAX_FILE_SIZE_MB:
            issues.append(f"Datei zu groß: {file_size_mb:.1f}MB (max: {Config.MAX_FILE_SIZE_MB}MB)")
        
        # Format prüfen
        format_type = production_result.get('format', '').lower()
        if format_type not in ['png', 'jpg', 'jpeg']:
            issues.append(f"Unerwartetes Format: {format_type}")
        
        # Qualitätsscore berechnen
        quality_score = self._calculate_quality_score(production_result, strategy)
        
        return ValidationResult(
            is_valid=len(issues) == 0,
            issues=issues,
            metrics={
                'width': width,
                'height': height,
                'format': format_type,
                'file_size_mb': file_size_mb,
                'url': production_result.get('secure_url')
            },
            quality_score=quality_score
        )
    
    def _calculate_quality_score(self, production_result: Dict, strategy: UpscalingStrategy) -> float:
        """Berechnet einen Qualitätsscore von 0-100."""
        score = 100.0
        
        # Auflösungs-Score
        width = production_result.get('width', 0)
        height = production_result.get('height', 0)
        target_width = strategy.target_dimensions['width']
        target_height = strategy.target_dimensions['height']
        
        resolution_ratio = min(width / target_width, height / target_height)
        if resolution_ratio < 0.8:
            score -= 30
        elif resolution_ratio < 0.9:
            score -= 15
        
        # Dateigröße-Score
        file_size_mb = production_result.get('bytes', 0) / (1024 * 1024)
        if file_size_mb > Config.MAX_FILE_SIZE_MB * 0.8:
            score -= 10
        
        # Format-Score
        format_type = production_result.get('format', '').lower()
        if format_type != 'png':
            score -= 5
        
        return max(0.0, score)
    
    async def process_artwork_upscaling(self, artwork: ArtworkRequest) -> Dict:
        """Verarbeitet das Upscaling für ein einzelnes Artwork."""
        try:
            # Status auf processing setzen
            await self._update_artwork_status(artwork.request_id, UpscalingStatus.PROCESSING)
            
            # Upscaling-Strategie erstellen
            strategy = self.create_upscaling_strategy(artwork)
            logger.info(f"Upscaling strategy for {artwork.request_id}: {strategy.quality_level}")
            
            # Produktionsbild erstellen
            production_result = self.create_production_image(artwork, strategy)
            
            # Qualität validieren
            validation = self.validate_production_image(production_result, strategy)
            
            # Status basierend auf Validierung setzen
            final_status = UpscalingStatus.COMPLETED if validation.is_valid else UpscalingStatus.QUALITY_ISSUES
            
            # Datenbank aktualisieren
            await self._update_artwork_with_production_data(
                artwork.request_id,
                production_result,
                strategy,
                validation,
                final_status
            )
            
            result = {
                'request_id': artwork.request_id,
                'status': final_status.value,
                'production_url': production_result.get('secure_url'),
                'strategy': asdict(strategy),
                'validation': asdict(validation)
            }
            
            # Bei erfolgreichem Abschluss Gelato benachrichtigen
            if final_status == UpscalingStatus.COMPLETED:
                await self._notify_gelato(artwork, production_result, strategy)
            
            return result
            
        except Exception as e:
            logger.error(f"Fehler beim Upscaling von {artwork.request_id}: {e}")
            await self._update_artwork_status(artwork.request_id, UpscalingStatus.FAILED, str(e))
            raise
    
    async def _update_artwork_status(self, request_id: str, status: UpscalingStatus, error_message: str = None):
        """Aktualisiert den Status eines Artworks in der Datenbank."""
        update_data = {
            'status': status.value,
            'processing_completed_at': datetime.utcnow().isoformat()
        }
        
        if error_message:
            update_data['error_message'] = error_message
        
        try:
            result = self.supabase.table('artwork_requests').update(update_data).eq('request_id', request_id).execute()
            logger.info(f"Status updated for {request_id}: {status.value}")
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren des Status: {e}")
    
    async def _update_artwork_with_production_data(self, request_id: str, production_result: Dict, 
                                                 strategy: UpscalingStrategy, validation: ValidationResult,
                                                 status: UpscalingStatus):
        """Aktualisiert Artwork mit vollständigen Produktionsdaten."""
        update_data = {
            'artwork_production_url': production_result.get('secure_url'),
            'production_cloudinary_id': production_result.get('asset_id'),
            'upscaling_strategy': json.dumps(asdict(strategy)),
            'production_quality_metrics': json.dumps(asdict(validation)),
            'status': status.value,
            'processing_completed_at': datetime.utcnow().isoformat()
        }
        
        try:
            result = self.supabase.table('artwork_requests').update(update_data).eq('request_id', request_id).execute()
            logger.info(f"Production data updated for {request_id}")
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren der Produktionsdaten: {e}")
    
    async def _notify_gelato(self, artwork: ArtworkRequest, production_result: Dict, strategy: UpscalingStrategy):
        """Benachrichtigt Gelato über das fertige Produktionsbild."""
        if not Config.GELATO_WEBHOOK_URL:
            logger.warning("Gelato Webhook URL nicht konfiguriert")
            return
        
        payload = {
            'request_id': artwork.request_id,
            'shopify_order_id': artwork.shopify_order_id,
            'production_image_url': production_result.get('secure_url'),
            'product_type': strategy.product_type.value,
            'dimensions': strategy.target_dimensions,
            'quality_level': strategy.quality_level
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {Config.GELATO_API_KEY}'
        }
        
        try:
            response = requests.post(Config.GELATO_WEBHOOK_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            logger.info(f"Gelato notified for {artwork.request_id}")
        except Exception as e:
            logger.error(f"Fehler beim Benachrichtigen von Gelato: {e}")

# Flask API
app = Flask(__name__)
CORS(app)

upscaling_service = CloudinaryUpscalingService()

@app.route('/health', methods=['GET'])
def health_check():
    """Gesundheitscheck für die API."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0'
    })

@app.route('/upscale/single', methods=['POST'])
async def upscale_single_artwork():
    """Upscaling für ein einzelnes Artwork."""
    try:
        data = request.get_json()
        
        artwork = ArtworkRequest(
            request_id=data['request_id'],
            shopify_order_id=data['shopify_order_id'],
            product_title=data['product_title'],
            variant_title=data.get('variant_title', ''),
            artwork_url=data['artwork_url'],
            pet_name=data['pet_name'],
            status=data.get('status', 'pending')
        )
        
        result = await upscaling_service.process_artwork_upscaling(artwork)
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Single Upscaling: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/upscale/batch', methods=['POST'])
async def upscale_batch_artworks():
    """Batch-Upscaling für mehrere Artworks."""
    try:
        data = request.get_json()
        artworks_data = data['artworks']
        
        results = []
        for artwork_data in artworks_data:
            artwork = ArtworkRequest(**artwork_data)
            try:
                result = await upscaling_service.process_artwork_upscaling(artwork)
                results.append(result)
            except Exception as e:
                results.append({
                    'request_id': artwork.request_id,
                    'status': 'failed',
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'results': results,
            'total_processed': len(results)
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Batch Upscaling: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/upscale/status/<request_id>', methods=['GET'])
def get_upscaling_status(request_id):
    """Status eines Upscaling-Prozesses abrufen."""
    try:
        result = upscaling_service.supabase.table('artwork_requests').select('*').eq('request_id', request_id).execute()
        
        if not result.data:
            return jsonify({
                'success': False,
                'error': 'Artwork nicht gefunden'
            }), 404
        
        artwork_data = result.data[0]
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'status': artwork_data.get('status'),
            'artwork_url': artwork_data.get('artwork_url'),
            'production_url': artwork_data.get('artwork_production_url'),
            'quality_metrics': json.loads(artwork_data.get('production_quality_metrics', '{}')),
            'processing_completed_at': artwork_data.get('processing_completed_at')
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen des Status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

