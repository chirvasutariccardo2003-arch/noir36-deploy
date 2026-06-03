from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent
env_file = ROOT_DIR / '.env'
if env_file.exists():
    load_dotenv(env_file)

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import bcrypt
import jwt
import uuid
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional

# MongoDB connection
mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
db_name = os.environ.get('DB_NAME', 'noir36')
client = AsyncIOMotorClient(mongo_url)
db = client[db_name]

app = FastAPI()
api_router = APIRouter(prefix="/api")

JWT_SECRET = os.environ.get('JWT_SECRET', 'change-me-in-production')
JWT_ALGORITHM = "HS256"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Utility Functions ---
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def create_access_token(user_id: str, email: str) -> str:
    payload = {"sub": user_id, "email": email, "exp": datetime.now(timezone.utc) + timedelta(hours=24), "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_admin(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = auth_header[7:]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = await db.users.find_one({"email": payload["email"]}, {"_id": 0, "password_hash": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

# --- Models ---
class LoginRequest(BaseModel):
    email: str
    password: str

class MenuItemCreate(BaseModel):
    name_it: str
    name_en: str
    description_it: str = ""
    description_en: str = ""
    price: float
    price_bottle: Optional[float] = None
    category: str
    allergens: List[str] = []
    is_cocktail_of_day: bool = False
    is_available: bool = True
    order: int = 0

class MenuItemUpdate(BaseModel):
    name_it: Optional[str] = None
    name_en: Optional[str] = None
    description_it: Optional[str] = None
    description_en: Optional[str] = None
    price: Optional[float] = None
    price_bottle: Optional[float] = None
    category: Optional[str] = None
    allergens: Optional[List[str]] = None
    is_cocktail_of_day: Optional[bool] = None
    is_available: Optional[bool] = None
    order: Optional[int] = None

class SettingsUpdate(BaseModel):
    is_open: Optional[bool] = None
    opening_time: Optional[str] = None
    closing_time: Optional[str] = None
    instagram: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None

class EventCreate(BaseModel):
    title_it: str
    title_en: str = ""
    description_it: str = ""
    description_en: str = ""
    date: str = ""
    time: str = ""
    is_active: bool = True

class EventUpdate(BaseModel):
    title_it: Optional[str] = None
    title_en: Optional[str] = None
    description_it: Optional[str] = None
    description_en: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    is_active: Optional[bool] = None

# --- Auth Routes ---
@api_router.post("/auth/login")
async def login(req: LoginRequest):
    user = await db.users.find_one({"email": req.email.lower()})
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Credenziali non valide")
    token = create_access_token(str(user["_id"]), user["email"])
    return {"token": token, "email": user["email"], "name": user.get("name", "Admin")}

@api_router.get("/auth/me")
async def get_me(user=Depends(get_current_admin)):
    return user

# --- Public Menu Routes ---
@api_router.get("/menu")
async def get_menu(category: Optional[str] = None):
    query = {"is_available": True}
    if category:
        query["category"] = category
    items = await db.menu_items.find(query, {"_id": 0}).sort("order", 1).to_list(500)
    return items

@api_router.get("/menu/categories")
async def get_categories():
    categories = await db.menu_items.distinct("category", {"is_available": True})
    order = ["signature", "special", "classici", "analcolici", "soft_drinks", "acqua", "taglieri", "shots"]
    return sorted(categories, key=lambda c: order.index(c) if c in order else 99)

@api_router.get("/menu/cocktail-of-day")
async def get_cocktail_of_day():
    item = await db.menu_items.find_one({"is_cocktail_of_day": True, "is_available": True}, {"_id": 0})
    return item

@api_router.get("/menu/allergens")
async def get_allergens():
    allergens = await db.menu_items.distinct("allergens")
    return [a for a in allergens if a]

# --- Public Events ---
@api_router.get("/events")
async def get_events():
    events = await db.events.find({"is_active": True}, {"_id": 0}).sort("date", 1).to_list(50)
    return events

# --- Public Settings ---
@api_router.get("/settings")
async def get_settings():
    settings = await db.settings.find_one({"id": "venue"}, {"_id": 0})
    if not settings:
        return {"id": "venue", "is_open": True, "opening_time": "17:00", "closing_time": "02:00", "instagram": "@noir36", "phone": "", "email": "", "address": "Via dell'Aquila 36, Pigneto - Roma"}
    return settings

# --- Admin Menu Routes ---
@api_router.get("/admin/menu")
async def admin_get_menu(user=Depends(get_current_admin)):
    items = await db.menu_items.find({}, {"_id": 0}).sort([("category", 1), ("order", 1)]).to_list(500)
    return items

@api_router.post("/admin/menu")
async def create_menu_item(item: MenuItemCreate, user=Depends(get_current_admin)):
    doc = item.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.menu_items.insert_one(doc)
    result = await db.menu_items.find_one({"id": doc["id"]}, {"_id": 0})
    return result

@api_router.put("/admin/menu/{item_id}")
async def update_menu_item(item_id: str, item: MenuItemUpdate, user=Depends(get_current_admin)):
    update_data = {k: v for k, v in item.model_dump(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nessun dato da aggiornare")
    # If setting cocktail of day, unset others
    if update_data.get("is_cocktail_of_day"):
        await db.menu_items.update_many({"is_cocktail_of_day": True}, {"$set": {"is_cocktail_of_day": False}})
    await db.menu_items.update_one({"id": item_id}, {"$set": update_data})
    result = await db.menu_items.find_one({"id": item_id}, {"_id": 0})
    if not result:
        raise HTTPException(status_code=404, detail="Item non trovato")
    return result

@api_router.delete("/admin/menu/{item_id}")
async def delete_menu_item(item_id: str, user=Depends(get_current_admin)):
    result = await db.menu_items.delete_one({"id": item_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Item non trovato")
    return {"message": "Eliminato con successo"}

# --- Admin Settings ---
@api_router.get("/admin/settings")
async def admin_get_settings(user=Depends(get_current_admin)):
    settings = await db.settings.find_one({"id": "venue"}, {"_id": 0})
    if not settings:
        return {"id": "venue", "is_open": True, "opening_time": "17:00", "closing_time": "02:00", "instagram": "@noir36", "phone": "", "email": "", "address": "Via dell'Aquila 36, Pigneto - Roma"}
    return settings

@api_router.put("/admin/settings")
async def update_settings(data: SettingsUpdate, user=Depends(get_current_admin)):
    update_data = {k: v for k, v in data.model_dump(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nessun dato da aggiornare")
    await db.settings.update_one({"id": "venue"}, {"$set": update_data}, upsert=True)
    result = await db.settings.find_one({"id": "venue"}, {"_id": 0})
    return result

# --- Admin Events ---
@api_router.get("/admin/events")
async def admin_get_events(user=Depends(get_current_admin)):
    events = await db.events.find({}, {"_id": 0}).sort("date", 1).to_list(50)
    return events

@api_router.post("/admin/events")
async def create_event(event: EventCreate, user=Depends(get_current_admin)):
    doc = event.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.events.insert_one(doc)
    return await db.events.find_one({"id": doc["id"]}, {"_id": 0})

@api_router.put("/admin/events/{event_id}")
async def update_event(event_id: str, event: EventUpdate, user=Depends(get_current_admin)):
    update_data = {k: v for k, v in event.model_dump(exclude_unset=True).items()}
    if not update_data:
        raise HTTPException(status_code=400, detail="Nessun dato da aggiornare")
    await db.events.update_one({"id": event_id}, {"$set": update_data})
    result = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not result:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    return result

@api_router.delete("/admin/events/{event_id}")
async def delete_event(event_id: str, user=Depends(get_current_admin)):
    result = await db.events.delete_one({"id": event_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Evento non trovato")
    return {"message": "Eliminato con successo"}

# --- Admin Set Cocktail of the Day ---
@api_router.put("/admin/cocktail-of-day/{item_id}")
async def set_cocktail_of_day(item_id: str, user=Depends(get_current_admin)):
    await db.menu_items.update_many({"is_cocktail_of_day": True}, {"$set": {"is_cocktail_of_day": False}})
    result = await db.menu_items.update_one({"id": item_id}, {"$set": {"is_cocktail_of_day": True}})
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Item non trovato")
    item = await db.menu_items.find_one({"id": item_id}, {"_id": 0})
    return item

# --- Seed Data ---
SEED_MENU = [
    # SIGNATURE COCKTAILS 10€
    {"name_it": "Amazon Noir", "name_en": "Amazon Noir", "description_it": "Rum scuro, passion fruit, lime, zucchero di canna, bitter", "description_en": "Dark rum, passion fruit, lime, cane sugar, bitters", "price": 10, "category": "signature", "allergens": [], "is_cocktail_of_day": True, "order": 1},
    {"name_it": "Passion Colada", "name_en": "Passion Colada", "description_it": "Rum bianco, passion fruit, cocco, lime", "description_en": "White rum, passion fruit, coconut, lime", "price": 10, "category": "signature", "allergens": [], "order": 2},
    {"name_it": "Blue Wave Mojito", "name_en": "Blue Wave Mojito", "description_it": "Rum bianco, lime, menta, Blue Curaçao, soda", "description_en": "White rum, lime, mint, Blue Curaçao, soda", "price": 10, "category": "signature", "allergens": [], "order": 3},
    # SPECIAL 9€
    {"name_it": "Purple Noir", "name_en": "Purple Noir", "description_it": "Vodka, succo di mirtillo, lime, sciroppo di zucchero, soda", "description_en": "Vodka, blueberry juice, lime, sugar syrup, soda", "price": 9, "category": "special", "allergens": [], "order": 1},
    {"name_it": "Red Noir", "name_en": "Red Noir", "description_it": "Vodka, frutti rossi, lime, Sprite", "description_en": "Vodka, red berries, lime, Sprite", "price": 9, "category": "special", "allergens": [], "order": 2},
    # CLASSICI
    {"name_it": "Spritz", "name_en": "Spritz", "description_it": "Aperol, prosecco, soda", "description_en": "Aperol, prosecco, soda", "price": 5.50, "category": "classici", "allergens": [], "order": 1},
    {"name_it": "Negroni", "name_en": "Negroni", "description_it": "Gin, Campari, Vermouth rosso", "description_en": "Gin, Campari, red Vermouth", "price": 7, "category": "classici", "allergens": [], "order": 2},
    {"name_it": "Mojito", "name_en": "Mojito", "description_it": "Rum bianco, lime, zucchero, menta, soda", "description_en": "White rum, lime, sugar, mint, soda", "price": 7, "category": "classici", "allergens": [], "order": 3},
    {"name_it": "Americano", "name_en": "Americano", "description_it": "Campari, Vermouth rosso, soda", "description_en": "Campari, red Vermouth, soda", "price": 7, "category": "classici", "allergens": [], "order": 4},
    {"name_it": "Gin Tonic", "name_en": "Gin & Tonic", "description_it": "Gin, acqua tonica", "description_en": "Gin, tonic water", "price": 7, "category": "classici", "allergens": [], "order": 5},
    {"name_it": "Margarita", "name_en": "Margarita", "description_it": "Tequila, lime, triple sec", "description_en": "Tequila, lime, triple sec", "price": 7, "category": "classici", "allergens": [], "order": 6},
    # ANALCOLICI
    {"name_it": "Ananastia", "name_en": "Ananastia", "description_it": "Ananas, arancia, menta, tè", "description_en": "Pineapple, orange, mint, tea", "price": 7, "category": "analcolici", "allergens": [], "order": 1},
    {"name_it": "Virgin Jungle", "name_en": "Virgin Jungle", "description_it": "Ananas, lime, menta, ginger beer", "description_en": "Pineapple, lime, mint, ginger beer", "price": 6, "category": "analcolici", "allergens": [], "order": 2},
    {"name_it": "Tutti Frutti Sour", "name_en": "Tutti Frutti Sour", "description_it": "Passion fruit, frutti rossi, lime, zucchero", "description_en": "Passion fruit, red berries, lime, sugar", "price": 6, "category": "analcolici", "allergens": [], "order": 3},
    {"name_it": "Avatar Mocktail", "name_en": "Avatar Mocktail", "description_it": "Red Bull bianca, Blue Curaçao analcolico, Sprite", "description_en": "White Red Bull, non-alcoholic Blue Curaçao, Sprite", "price": 6, "category": "analcolici", "allergens": [], "order": 4},
    # SOFT DRINKS
    {"name_it": "Coca-Cola", "name_en": "Coca-Cola", "description_it": "", "description_en": "", "price": 3, "category": "soft_drinks", "allergens": [], "order": 1},
    {"name_it": "Coca-Cola Zero", "name_en": "Coca-Cola Zero", "description_it": "", "description_en": "", "price": 3, "category": "soft_drinks", "allergens": [], "order": 2},
    {"name_it": "Fanta", "name_en": "Fanta", "description_it": "", "description_en": "", "price": 3, "category": "soft_drinks", "allergens": [], "order": 3},
    {"name_it": "Estathé", "name_en": "Estathé", "description_it": "", "description_en": "", "price": 3, "category": "soft_drinks", "allergens": [], "order": 4},
    {"name_it": "Crodino", "name_en": "Crodino", "description_it": "", "description_en": "", "price": 3.50, "category": "soft_drinks", "allergens": [], "order": 5},
    {"name_it": "Red Bull", "name_en": "Red Bull", "description_it": "", "description_en": "", "price": 4, "category": "soft_drinks", "allergens": [], "order": 6},
    # ACQUA
    {"name_it": "Acqua Liscia", "name_en": "Still Water", "description_it": "", "description_en": "", "price": 1.50, "category": "acqua", "allergens": [], "order": 1},
    {"name_it": "Acqua Frizzante", "name_en": "Sparkling Water", "description_it": "", "description_en": "", "price": 1.50, "category": "acqua", "allergens": [], "order": 2},
    # TAGLIERI
    {"name_it": "Tagliere Piccolo", "name_en": "Small Board", "description_it": "Selezione di salumi, formaggi e accompagnamenti", "description_en": "Selection of cured meats, cheeses and sides", "price": 10, "category": "taglieri", "allergens": ["lattosio", "glutine"], "order": 1},
    {"name_it": "Tagliere Grande", "name_en": "Large Board", "description_it": "Selezione abbondante di salumi, formaggi e accompagnamenti", "description_en": "Generous selection of cured meats, cheeses and sides", "price": 15, "category": "taglieri", "allergens": ["lattosio", "glutine"], "order": 2},
    # SHOTS
    {"name_it": "Shot Base", "name_en": "Basic Shot", "description_it": "Tequila, vodka liscia, ecc.", "description_en": "Tequila, plain vodka, etc.", "price": 3, "category": "shots", "allergens": [], "order": 1},
    {"name_it": "Shot Normali", "name_en": "Regular Shot", "description_it": "Kamikaze, liquori vari", "description_en": "Kamikaze, various liqueurs", "price": 4, "category": "shots", "allergens": [], "order": 2},
    {"name_it": "Shot Special", "name_en": "Special Shot", "description_it": "Nutella shot, shot particolari", "description_en": "Nutella shot, special shots", "price": 5, "category": "shots", "allergens": ["lattosio"], "order": 3},
]

async def seed_admin():
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@noir36.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Noir36Admin!")
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "name": "Admin Noir36",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"Admin user created: {admin_email}")
    elif not verify_password(admin_password, existing["password_hash"]):
        await db.users.update_one({"email": admin_email}, {"$set": {"password_hash": hash_password(admin_password)}})
        logger.info("Admin password updated")

async def seed_menu():
    count = await db.menu_items.count_documents({})
    if count == 0:
        for item in SEED_MENU:
            item["id"] = str(uuid.uuid4())
            item["is_available"] = True
            item["created_at"] = datetime.now(timezone.utc).isoformat()
            if "is_cocktail_of_day" not in item:
                item["is_cocktail_of_day"] = False
            if "price_bottle" not in item:
                item["price_bottle"] = None
        await db.menu_items.insert_many(SEED_MENU)
        logger.info(f"Seeded {len(SEED_MENU)} menu items")

async def seed_settings():
    existing = await db.settings.find_one({"id": "venue"})
    if not existing:
        await db.settings.insert_one({
            "id": "venue",
            "is_open": True,
            "opening_time": "17:00",
            "closing_time": "02:00",
            "instagram": "@noir36",
            "phone": "",
            "email": "",
            "address": "Via dell'Aquila 36, Pigneto - Roma"
        })
        logger.info("Seeded venue settings")

async def seed_events():
    count = await db.events.count_documents({})
    if count == 0:
        events = [
            {"id": str(uuid.uuid4()), "title_it": "Tropical Night", "title_en": "Tropical Night", "description_it": "Serata a tema tropicale con DJ set e cocktail speciali della giungla", "description_en": "Tropical themed night with DJ set and special jungle cocktails", "date": "2026-05-17", "time": "21:00", "is_active": True, "created_at": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title_it": "Aperitivo Amazzonico", "title_en": "Amazonian Aperitivo", "description_it": "Aperitivo speciale dalle 17 alle 20 con tagliere + cocktail signature a 15€", "description_en": "Special aperitivo from 5 to 8 PM with board + signature cocktail for 15€", "date": "2026-05-22", "time": "17:00", "is_active": True, "created_at": datetime.now(timezone.utc).isoformat()},
            {"id": str(uuid.uuid4()), "title_it": "Live Music Friday", "title_en": "Live Music Friday", "description_it": "Musica dal vivo ogni venerdì sera con artisti locali del Pigneto", "description_en": "Live music every Friday night with local Pigneto artists", "date": "2026-05-23", "time": "22:00", "is_active": True, "created_at": datetime.now(timezone.utc).isoformat()},
        ]
        await db.events.insert_many(events)
        logger.info(f"Seeded {len(events)} events")

@app.on_event("startup")
async def startup():
    await db.users.create_index("email", unique=True)
    await db.menu_items.create_index("category")
    await db.menu_items.create_index("id", unique=True)
    await db.events.create_index("id", unique=True)
    await seed_admin()
    await seed_menu()
    await seed_settings()
    await seed_events()
    # Write test credentials
    os.makedirs("/app/memory", exist_ok=True)
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@noir36.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "Noir36Admin!")
    with open("/app/memory/test_credentials.md", "w") as f:
        f.write(f"# Test Credentials\n\n## Admin\n- Email: {admin_email}\n- Password: {admin_password}\n- Role: admin\n\n## Auth Endpoints\n- POST /api/auth/login\n- GET /api/auth/me\n\n## Menu Endpoints\n- GET /api/menu\n- GET /api/menu/categories\n- GET /api/menu/cocktail-of-day\n- GET /api/menu/allergens\n- GET /api/admin/menu (auth required)\n- POST /api/admin/menu (auth required)\n- PUT /api/admin/menu/{{id}} (auth required)\n- DELETE /api/admin/menu/{{id}} (auth required)\n\n## Settings Endpoints\n- GET /api/settings (public)\n- GET /api/admin/settings (auth required)\n- PUT /api/admin/settings (auth required)\n")
    logger.info("Startup complete")

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static build (for Railway/Docker deployment)
STATIC_DIR = ROOT_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR / "static")), name="static-assets")
    # Serve frames
    FRAMES_DIR = STATIC_DIR / "frames"
    if FRAMES_DIR.exists():
        app.mount("/frames", StaticFiles(directory=str(FRAMES_DIR)), name="frames")
    # Serve other public files
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(STATIC_DIR / "index.html"))

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
