# SmartLOFO Backend Guide

SmartLOFO now supports **TWO database backends** with identical functionality:

## 🗄️ Available Backends

### 1. MongoDB Backend (Default)
- **File**: `server.py`
- **Database**: MongoDB
- **Port**: 8001
- **Use Case**: Scalable, production-ready NoSQL database

### 2. SQLite Backend (Alternative)
- **File**: `server_sqlite.py`
- **Database**: SQLite (file-based)
- **Port**: 8002 (when running both)
- **Use Case**: Lightweight, no external database required, perfect for development and small deployments

## 🚀 How to Switch Between Backends

### Option 1: Run MongoDB Backend (Current Default)
```bash
# Already configured in supervisor
cd /app/backend
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Option 2: Run SQLite Backend
```bash
# Stop MongoDB backend first
sudo supervisorctl stop backend

# Run SQLite backend
cd /app/backend
uvicorn server_sqlite:app --host 0.0.0.0 --port 8001 --reload
```

### Option 3: Run Both Backends Simultaneously
You can run both backends on different ports for testing:

```bash
# MongoDB on port 8001 (already running via supervisor)
# SQLite on port 8002
cd /app/backend
uvicorn server_sqlite:app --host 0.0.0.0 --port 8002 --reload &
```

Then update frontend `.env`:
- For MongoDB: `REACT_APP_BACKEND_URL=http://your-domain/api`
- For SQLite: `REACT_APP_BACKEND_URL=http://your-domain:8002/api`

## 📊 Feature Comparison

Both backends support **100% identical features**:

| Feature | MongoDB | SQLite |
|---------|---------|--------|
| User Authentication (JWT) | ✅ | ✅ |
| Report Lost Items | ✅ | ✅ |
| Report Found Items | ✅ | ✅ |
| AI Image Recognition (Gemini) | ✅ | ✅ |
| Auto Description Generation | ✅ | ✅ |
| Smart Matching Algorithm | ✅ | ✅ |
| Email Notifications | ✅ | ✅ |
| GPS Location Support | ✅ | ✅ |
| Search & Filters | ✅ | ✅ |
| Profile Management | ✅ | ✅ |

## 🔧 Database Details

### MongoDB Backend
- **Connection**: Requires MongoDB service running
- **Database Name**: Configured in `.env` (`DB_NAME`)
- **Collections**: `users`, `items`, `matches`
- **Data Location**: MongoDB server storage

### SQLite Backend
- **Connection**: No external service required
- **Database File**: `smartlofo.db` (auto-created in `/app/backend/`)
- **Tables**: `users`, `items`, `matches`
- **Data Location**: Single file in backend directory

## 📝 API Endpoints

Both backends expose the **exact same API endpoints**:

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `GET /api/auth/me` - Get current user
- `PUT /api/auth/profile` - Update profile

### Items
- `POST /api/items` - Create lost/found item
- `GET /api/items` - Get all items (with filters)
- `GET /api/items/my-items` - Get user's items
- `GET /api/items/{item_id}` - Get specific item
- `DELETE /api/items/{item_id}` - Delete item

### Matches
- `GET /api/matches` - Get user's matches

### Health Check
- `GET /api/` - API status

## 🎯 When to Use Which Backend?

### Use MongoDB Backend When:
- 🌐 Deploying to production
- 📈 Expecting high traffic/scale
- 🔄 Need advanced querying features
- ☁️ Already have MongoDB infrastructure

### Use SQLite Backend When:
- 💻 Development and testing
- 📦 Single-server deployment
- 🚀 Quick setup without external dependencies
- 📊 Small to medium data volumes (< 100K items)
- 🎓 Educational or demo purposes

## 🔄 Migrating Data

To migrate data between backends:

### Export from MongoDB
```bash
mongoexport --db test_database --collection users --out users.json
mongoexport --db test_database --collection items --out items.json
mongoexport --db test_database --collection matches --out matches.json
```

### Import to SQLite
(Use Python script to parse JSON and insert into SQLite)

## ⚙️ Environment Variables

Both backends use the same `.env` file:

```env
# JWT Configuration
JWT_SECRET=smartlofo_secret_key_2025_ai_based_system

# Email Configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password

# AI Configuration
EMERGENT_LLM_KEY=your-gemini-key

# CORS
CORS_ORIGINS=*

# MongoDB specific (only for server.py)
MONGO_URL=mongodb://localhost:27017
DB_NAME=test_database
```

## 🧪 Testing Both Backends

Test health endpoint for each:

```bash
# MongoDB backend
curl http://localhost:8001/api/

# SQLite backend
curl http://localhost:8002/api/
```

Expected response:
```json
{
  "message": "SmartLOFO API is running",
  "version": "1.0",
  "database": "MongoDB" or "SQLite"
}
```

## 📚 Additional Notes

- **Performance**: MongoDB is faster for complex queries at scale, SQLite is faster for simple operations
- **Concurrency**: MongoDB handles concurrent writes better
- **Backup**: SQLite = copy one file, MongoDB = use mongodump
- **No Code Changes**: Frontend works with both backends without any modifications!

---

**Current Configuration**: MongoDB backend is active by default via supervisor on port 8001.
