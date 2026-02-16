from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, UploadFile, File, Form
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
from jwt import PyJWTError as JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import base64
from PIL import Image
from io import BytesIO
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
import asyncio
import sqlite3
import json
from contextlib import contextmanager

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# SQLite Database path
DB_PATH = ROOT_DIR / 'smartlofo.db'

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'your-secret-key-change-in-production')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_DAYS = 30

# Email Configuration
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USER = os.environ.get('EMAIL_USER')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')

# Create the main app
app = FastAPI()
api_router = APIRouter(prefix="/api")

# Security
security = HTTPBearer()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============ DATABASE SETUP ============

@contextmanager
def get_db():
    """Get database connection"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize SQLite database with tables"""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Users table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        
        # Items table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                category TEXT NOT NULL,
                location TEXT NOT NULL,
                gps_coords TEXT,
                image_base64 TEXT,
                status TEXT NOT NULL,
                ai_extracted_features TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Matches table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY,
                lost_item_id TEXT NOT NULL,
                found_item_id TEXT NOT NULL,
                similarity_score REAL NOT NULL,
                notified INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (lost_item_id) REFERENCES items (id),
                FOREIGN KEY (found_item_id) REFERENCES items (id)
            )
        ''')
        
        conn.commit()
        logger.info("SQLite database initialized successfully")

# Initialize database on startup
init_db()


# ============ MODELS ============

class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name: str
    email: str
    created_at: str

class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None

class ItemCreate(BaseModel):
    type: str  # "lost" or "found"
    title: str
    description: Optional[str] = None
    category: str
    location: str
    gps_coords: Optional[dict] = None
    image_base64: Optional[str] = None

class ItemResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    user_name: str
    type: str
    title: str
    description: str
    category: str
    location: str
    gps_coords: Optional[dict] = None
    image_base64: Optional[str] = None
    status: str
    ai_extracted_features: Optional[str] = None
    created_at: str

class MatchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    lost_item: ItemResponse
    found_item: ItemResponse
    similarity_score: float
    created_at: str


# ============ UTILITIES ============

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRATION_DAYS)
    to_encode = {"sub": user_id, "exp": expire}
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def row_to_dict(row):
    """Convert SQLite row to dictionary"""
    if row is None:
        return None
    return dict(row)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return row_to_dict(user)

async def send_email(to_email: str, subject: str, body: str):
    """Send email notification"""
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_USER, to_email, text)
        server.quit()
        logger.info(f"Email sent to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")

async def analyze_image_with_gemini(image_base64: str) -> dict:
    """Use Gemini to extract features and description from image"""
    try:
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.5-flash')

        # Decode base64 image
        image_data = base64.b64decode(image_base64)
        image = Image.open(BytesIO(image_data))

        prompt = "Analyze this image and provide: 1) A detailed description of the item (color, brand, condition, distinctive features) 2) Category (e.g., Electronics, Accessories, Documents, Clothing, Keys, Bags) 3) Key features for matching. Format as: DESCRIPTION: [description] | CATEGORY: [category] | FEATURES: [key features]"

        response = model.generate_content([prompt, image])
        return {"success": True, "analysis": response.text}
    except Exception as e:
        logger.error(f"Gemini analysis error: {str(e)}")
        return {"success": False, "error": str(e)}

async def calculate_similarity(item1_image: str, item2_image: str, item1_features: str = "", item2_features: str = "") -> float:
    """Calculate similarity between two items by comparing their images directly"""
    if not item1_image or not item2_image:
        return 0.5  # Default similarity if no images available

    try:
        # Use Gemini to compare images directly
        genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.5-flash')

        # Decode base64 images
        image1_data = base64.b64decode(item1_image)
        image2_data = base64.b64decode(item2_image)
        image1 = Image.open(BytesIO(image1_data))
        image2 = Image.open(BytesIO(image2_data))

        prompt = """Compare these two images and determine how similar the items are as a percentage (0-100).
        Consider if they appear to be the same object, same item type, color, brand, condition, and distinctive features.
        If the images show identical or nearly identical items, give a high percentage (90-100%).
        If they are similar but different items, give a moderate percentage.
        If they are completely different items, give a low percentage (0-20%).

        Return only a number between 0 and 100 representing the similarity percentage."""

        response = model.generate_content([prompt, image1, image2])
        similarity_text = response.text.strip()

        # Extract number from response
        import re
        match = re.search(r'(\d+(?:\.\d+)?)', similarity_text)
        if match:
            similarity = float(match.group(1))
            return min(max(similarity / 100.0, 0.0), 1.0)  # Ensure between 0 and 1
        else:
            return 0.5  # Default if parsing fails
    except Exception as e:
        logger.error(f"Error calculating similarity: {str(e)}")
        return 0.5  # Default similarity on error

async def find_matches(item_id: str, item_type: str):
    """Find potential matches between lost and found items"""
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Get current item
            cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            current_item = cursor.fetchone()
            if not current_item:
                return
            current_item = row_to_dict(current_item)

            # Search for opposite type
            opposite_type = "found" if item_type == "lost" else "lost"
            cursor.execute("""
                SELECT * FROM items
                WHERE type = ? AND status = 'active' AND category = ?
            """, (opposite_type, current_item.get("category")))
            potential_matches = [row_to_dict(row) for row in cursor.fetchall()]

            # AI-based matching
            for match in potential_matches:
                # Check if match already exists
                lost_id = item_id if item_type == "lost" else match["id"]
                found_id = match["id"] if item_type == "lost" else item_id

                cursor.execute("""
                    SELECT * FROM matches
                    WHERE lost_item_id = ? AND found_item_id = ?
                """, (lost_id, found_id))
                existing_match = cursor.fetchone()

                if not existing_match:
                    # Calculate AI-based similarity score by comparing images directly
                    similarity_score = await calculate_similarity(
                        current_item.get("image_base64", ""),
                        match.get("image_base64", ""),
                        current_item.get("ai_extracted_features", ""),
                        match.get("ai_extracted_features", "")
                    )
                    
                    match_id = str(uuid.uuid4())
                    created_at = datetime.now(timezone.utc).isoformat()
                    
                    cursor.execute("""
                        INSERT INTO matches (id, lost_item_id, found_item_id, similarity_score, notified, created_at)
                        VALUES (?, ?, ?, ?, 0, ?)
                    """, (match_id, lost_id, found_id, similarity_score, created_at))
                    conn.commit()
                    
                    # Send email notification to both users
                    lost_item = current_item if item_type == "lost" else match
                    found_item = match if item_type == "lost" else current_item
                    
                    cursor.execute("SELECT * FROM users WHERE id = ?", (lost_item["user_id"],))
                    lost_user = row_to_dict(cursor.fetchone())
                    
                    cursor.execute("SELECT * FROM users WHERE id = ?", (found_item["user_id"],))
                    found_user = row_to_dict(cursor.fetchone())
                    
                    if lost_user and found_user:
                        # Notify lost item owner
                        await send_email(
                            lost_user["email"],
                            "Potential Match Found - SmartLOFO",
                            f"""
                            <h2>Great News!</h2>
                            <p>We found a potential match for your lost item: <strong>{lost_item['title']}</strong></p>
                            <p><strong>Found Item:</strong> {found_item['title']}</p>
                            <p><strong>Location:</strong> {found_item['location']}</p>
                            <p><strong>Contact:</strong> {found_user['name']} ({found_user['email']})</p>
                            <p>Match Confidence: {int(similarity_score * 100)}%</p>
                            <p>Visit SmartLOFO to view more details.</p>
                            """
                        )
                        
                        # Notify found item owner
                        await send_email(
                            found_user["email"],
                            "Item Match Found - SmartLOFO",
                            f"""
                            <h2>Potential Owner Found!</h2>
                            <p>Your found item <strong>{found_item['title']}</strong> might belong to someone!</p>
                            <p><strong>Lost Item:</strong> {lost_item['title']}</p>
                            <p><strong>Owner:</strong> {lost_user['name']} ({lost_user['email']})</p>
                            <p>Match Confidence: {int(similarity_score * 100)}%</p>
                            <p>Visit SmartLOFO to view more details.</p>
                            """
                        )
                        
                        cursor.execute("""
                            UPDATE matches SET notified = 1 WHERE id = ?
                        """, (match_id,))
                        conn.commit()
    except Exception as e:
        logger.error(f"Error finding matches: {str(e)}")


# ============ AUTH ROUTES ============

@api_router.post("/auth/register")
async def register(user: UserCreate):
    logger.info(f"Registration attempt for email: {user.email}")
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Check if user exists
            cursor.execute("SELECT * FROM users WHERE email = ?", (user.email,))
            existing = cursor.fetchone()
            if existing:
                logger.warning(f"Registration failed: Email {user.email} already registered")
                raise HTTPException(status_code=400, detail="Email already registered")

            # Create user
            user_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()

            cursor.execute("""
                INSERT INTO users (id, name, email, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, user.name, user.email, hash_password(user.password), created_at))
            conn.commit()

            # Create token
            token = create_access_token(user_id)

            logger.info(f"User registered successfully: {user.email}")
            return {
                "token": token,
                "user": {
                    "id": user_id,
                    "name": user.name,
                    "email": user.email,
                    "created_at": created_at
                }
            }
    except Exception as e:
        logger.error(f"Registration error for {user.email}: {str(e)}")
        raise

@api_router.post("/auth/login")
async def login(credentials: UserLogin):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (credentials.email,))
        user = cursor.fetchone()
        
    if not user or not verify_password(credentials.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    user = row_to_dict(user)
    token = create_access_token(user["id"])
    
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "created_at": user["created_at"]
        }
    }

@api_router.get("/auth/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    return current_user

@api_router.put("/auth/profile", response_model=UserResponse)
async def update_profile(update: UserUpdate, current_user: dict = Depends(get_current_user)):
    update_data = update.model_dump(exclude_unset=True)
    
    if update_data:
        with get_db() as conn:
            cursor = conn.cursor()
            
            # Build update query
            set_clauses = []
            values = []
            for key, value in update_data.items():
                set_clauses.append(f"{key} = ?")
                values.append(value)
            values.append(current_user["id"])
            
            query = f"UPDATE users SET {', '.join(set_clauses)} WHERE id = ?"
            cursor.execute(query, values)
            conn.commit()
            
            # Get updated user
            cursor.execute("SELECT * FROM users WHERE id = ?", (current_user["id"],))
            updated_user = row_to_dict(cursor.fetchone())
    else:
        updated_user = current_user
    
    return updated_user


# ============ ITEM ROUTES ============

@api_router.post("/items", response_model=ItemResponse)
async def create_item(item: ItemCreate, current_user: dict = Depends(get_current_user)):
    # Analyze image with Gemini if provided
    ai_features = None
    auto_description = item.description or ""

    if item.image_base64:
        analysis = await analyze_image_with_gemini(item.image_base64)
        if analysis.get("success"):
            ai_features = analysis["analysis"]
            # Always generate AI description and combine with user description
            ai_description = ai_features[:200]
            if auto_description:
                auto_description = f"{auto_description}\n\nAI Analysis: {ai_description}"
            else:
                auto_description = ai_description
    
    item_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    gps_coords_json = json.dumps(item.gps_coords) if item.gps_coords else None
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO items (id, user_id, user_name, type, title, description, category, 
                             location, gps_coords, image_base64, status, ai_extracted_features, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """, (item_id, current_user["id"], current_user["name"], item.type, item.title,
              auto_description or "", item.category, item.location, gps_coords_json,
              item.image_base64, ai_features, created_at))
        conn.commit()
        
        # Get created item
        cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item_doc = row_to_dict(cursor.fetchone())
    
    # Parse gps_coords back to dict
    if item_doc.get("gps_coords"):
        item_doc["gps_coords"] = json.loads(item_doc["gps_coords"])
    
    # Find matches asynchronously
    asyncio.create_task(find_matches(item_id, item.type))
    
    return item_doc

@api_router.get("/items", response_model=List[ItemResponse])
async def get_items(
    type: Optional[str] = None,
    category: Optional[str] = None,
    location: Optional[str] = None,
    search: Optional[str] = None
):
    with get_db() as conn:
        cursor = conn.cursor()
        
        query = "SELECT * FROM items WHERE status = 'active'"
        params = []
        
        if type:
            query += " AND type = ?"
            params.append(type)
        if category:
            query += " AND category = ?"
            params.append(category)
        if location:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")
        if search:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        
        query += " ORDER BY created_at DESC LIMIT 100"
        
        cursor.execute(query, params)
        items = [row_to_dict(row) for row in cursor.fetchall()]
    
    # Parse gps_coords
    for item in items:
        if item.get("gps_coords"):
            item["gps_coords"] = json.loads(item["gps_coords"])
    
    return items

@api_router.get("/items/my-items", response_model=List[ItemResponse])
async def get_my_items(current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM items WHERE user_id = ? AND status = 'active' ORDER BY created_at DESC LIMIT 100
        """, (current_user["id"],))
        items = [row_to_dict(row) for row in cursor.fetchall()]

    # Parse gps_coords
    for item in items:
        if item.get("gps_coords"):
            item["gps_coords"] = json.loads(item["gps_coords"])

    return items

@api_router.get("/items/{item_id}", response_model=ItemResponse)
async def get_item(item_id: str):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
        item = cursor.fetchone()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item = row_to_dict(item)
    if item.get("gps_coords"):
        item["gps_coords"] = json.loads(item["gps_coords"])
    
    return item

@api_router.delete("/items/{item_id}")
async def delete_item(item_id: str, current_user: dict = Depends(get_current_user)):
    logger.info(f"Delete attempt for item {item_id} by user {current_user['id']}")
    try:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            item = cursor.fetchone()

            if not item:
                logger.warning(f"Item {item_id} not found")
                raise HTTPException(status_code=404, detail="Item not found")

            item = row_to_dict(item)
            if item["user_id"] != current_user["id"]:
                logger.warning(f"User {current_user['id']} not authorized to delete item {item_id}")
                raise HTTPException(status_code=403, detail="Not authorized to delete this item")

            cursor.execute("UPDATE items SET status = 'deleted' WHERE id = ?", (item_id,))
            conn.commit()
            logger.info(f"Item {item_id} deleted successfully")

        return {"message": "Item deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting item {item_id}: {str(e)}")
        raise


# ============ MATCH ROUTES ============

@api_router.get("/matches", response_model=List[MatchResponse])
async def get_matches(current_user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Find user's items
        cursor.execute("SELECT id FROM items WHERE user_id = ?", (current_user["id"],))
        user_item_ids = [row["id"] for row in cursor.fetchall()]
        
        if not user_item_ids:
            return []
        
        # Find matches
        placeholders = ','.join('?' * len(user_item_ids))
        cursor.execute(f"""
            SELECT * FROM matches 
            WHERE lost_item_id IN ({placeholders}) OR found_item_id IN ({placeholders})
        """, user_item_ids + user_item_ids)
        matches = [row_to_dict(row) for row in cursor.fetchall()]
        
        # Populate with item details
        result = []
        for match in matches:
            cursor.execute("SELECT * FROM items WHERE id = ?", (match["lost_item_id"],))
            lost_item = row_to_dict(cursor.fetchone())
            
            cursor.execute("SELECT * FROM items WHERE id = ?", (match["found_item_id"],))
            found_item = row_to_dict(cursor.fetchone())
            
            if lost_item and found_item:
                # Parse gps_coords
                if lost_item.get("gps_coords"):
                    lost_item["gps_coords"] = json.loads(lost_item["gps_coords"])
                if found_item.get("gps_coords"):
                    found_item["gps_coords"] = json.loads(found_item["gps_coords"])
                
                result.append({
                    "id": match["id"],
                    "lost_item": lost_item,
                    "found_item": found_item,
                    "similarity_score": match["similarity_score"],
                    "created_at": match["created_at"]
                })
    
    return result


# ============ RE-MATCH ROUTES ============

@api_router.post("/matches/{match_id}/rematch")
async def rematch_items(match_id: str, current_user: dict = Depends(get_current_user)):
    """Re-run AI matching for a specific match to update confidence score"""
    logger.info(f"AI is rematching items for match {match_id} by user {current_user['id']}")
    try:
        with get_db() as conn:
            cursor = conn.cursor()

            # Get the match details
            cursor.execute("SELECT * FROM matches WHERE id = ?", (match_id,))
            match = cursor.fetchone()
            if not match:
                raise HTTPException(status_code=404, detail="Match not found")

            match = row_to_dict(match)

            # Verify user has access to this match
            cursor.execute("SELECT id FROM items WHERE id = ? AND user_id = ?", (match["lost_item_id"], current_user["id"]))
            lost_access = cursor.fetchone()
            cursor.execute("SELECT id FROM items WHERE id = ? AND user_id = ?", (match["found_item_id"], current_user["id"]))
            found_access = cursor.fetchone()

            if not lost_access and not found_access:
                raise HTTPException(status_code=403, detail="Not authorized to rematch this item")

            # Get item details
            cursor.execute("SELECT * FROM items WHERE id = ?", (match["lost_item_id"],))
            lost_item = row_to_dict(cursor.fetchone())
            cursor.execute("SELECT * FROM items WHERE id = ?", (match["found_item_id"],))
            found_item = row_to_dict(cursor.fetchone())

            if not lost_item or not found_item:
                raise HTTPException(status_code=404, detail="Items not found")

            # Re-calculate similarity
            similarity_score = await calculate_similarity(
                lost_item.get("image_base64", ""),
                found_item.get("image_base64", ""),
                lost_item.get("ai_extracted_features", ""),
                found_item.get("ai_extracted_features", "")
            )

            # Update the match with new similarity score
            cursor.execute("""
                UPDATE matches SET similarity_score = ? WHERE id = ?
            """, (similarity_score, match_id))
            conn.commit()

            return {
                "message": "Match confidence updated successfully",
                "new_confidence": similarity_score,
                "match_id": match_id
            }

    except Exception as e:
        logger.error(f"Error rematching items: {str(e)}")
        raise


@api_router.get("/")
async def root():
    return {"message": "SmartLOFO API (SQLite) is running", "version": "1.0", "database": "SQLite"}


# Include router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[
        "http://localhost:3000",
        "https://zbfk9g1k-8000.asse.devtunnels.ms",
        "http://localhost:3000/",
        "https://smartlofobackend-dqapnowpq-smartlofos-projects.vercel.app",
        "https://smartlofofrontend1-t2ofvysr4-smartlofos-projects.vercel.app",
        "https://smartlofofrontend1.vercel.app",
        "https://zbfk9g1k-8000.asse.devtunnels.ms/",
        "https://smartlofobackend-production.up.railway.app",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
