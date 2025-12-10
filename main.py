from fastapi import FastAPI, Depends, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, date, time
from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum
import asyncpg
import redis.asyncio as aioredis
import os
import json
import logging
from jose import JWTError, jwt
import sys
sys.path.append(os.path.dirname(__file__))
from utils.http_client import validate_user, get_active_programs

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("schedule-service")

# Configuration
# Database configuration using connection string
# For production: Set DATABASE_URL with sslmode=require for TLS
# For local dev: Set DATABASE_URL without sslmode for plain connection
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-jwt-key")

# Global connections
db_pool = None
redis_client = None

# Enums
class BookingType(str, Enum):
    one_on_one = "one_on_one"
    group_class = "group_class"

class BookingStatus(str, Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"

class SessionStatus(str, Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"

# Models
class AvailabilityCreate(BaseModel):
    gym_id: Optional[str] = None
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: time
    end_time: time
    is_recurring: bool = True
    specific_date: Optional[date] = None
    max_slots: int = Field(default=1, ge=1)

class BookingCreate(BaseModel):
    type: BookingType
    trainer_id: str
    gym_id: Optional[str] = None
    booking_date: date
    start_time: time
    end_time: time
    notes: Optional[str] = None

class BookingUpdate(BaseModel):
    booking_date: Optional[date] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None

class CancelBooking(BaseModel):
    cancellation_reason: Optional[str] = None

class GroupSessionCreate(BaseModel):
    trainer_id: str
    session_name: str
    description: str
    max_participants: int
    gym_id: str
    session_date: date
    start_time: time
    end_time: time

# Database initialization
async def init_db():
    global db_pool
    # Use connection string - TLS enabled if sslmode in URL
    # DevOps will handle proper certificates in production
    db_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=5,
        max_size=20,
        ssl='prefer'  # Use SSL if available, allow self-signed certs
    )
    ssl_status = "with TLS" if "sslmode" in DATABASE_URL else "without TLS"
    logger.info(f"Database pool created {ssl_status}")

    # Run migrations
    await run_migrations()

async def close_db():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database pool closed")

async def run_migrations():
    async with db_pool.acquire() as conn:
        try:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS migrations (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) UNIQUE NOT NULL,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

                CREATE TABLE IF NOT EXISTS availability (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    trainer_id UUID NOT NULL,
                    gym_id UUID,
                    day_of_week INTEGER CHECK (day_of_week >= 0 AND day_of_week <= 6),
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    is_recurring BOOLEAN DEFAULT true,
                    specific_date DATE,
                    max_slots INTEGER DEFAULT 1,
                    is_active BOOLEAN DEFAULT true,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_availability_trainer ON availability(trainer_id);
                CREATE INDEX IF NOT EXISTS idx_availability_date ON availability(specific_date);

                CREATE TABLE IF NOT EXISTS bookings (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    type VARCHAR(20) CHECK (type IN ('one_on_one', 'group_class')),
                    trainer_id UUID NOT NULL,
                    client_id UUID NOT NULL,
                    gym_id UUID,
                    booking_date DATE NOT NULL,
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    status VARCHAR(20) CHECK (status IN ('scheduled', 'completed', 'cancelled', 'no_show')) DEFAULT 'scheduled',
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    cancelled_at TIMESTAMP,
                    cancellation_reason TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_bookings_client ON bookings(client_id);
                CREATE INDEX IF NOT EXISTS idx_bookings_trainer ON bookings(trainer_id);
                CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(booking_date);
                CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);

                CREATE TABLE IF NOT EXISTS group_sessions (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    trainer_id UUID NOT NULL,
                    session_name VARCHAR(255) NOT NULL,
                    description TEXT,
                    max_participants INTEGER NOT NULL,
                    current_participants INTEGER DEFAULT 0,
                    gym_id UUID NOT NULL,
                    session_date DATE NOT NULL,
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL,
                    status VARCHAR(20) CHECK (status IN ('scheduled', 'completed', 'cancelled')) DEFAULT 'scheduled',
                    enrolled_clients UUID[] DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_group_sessions_trainer ON group_sessions(trainer_id);
                CREATE INDEX IF NOT EXISTS idx_group_sessions_date ON group_sessions(session_date);
            """)
            logger.info("Migrations completed")
        except Exception as e:
            logger.error(f"Migration error: {e}")

# Redis initialization
async def init_redis():
    global redis_client
    redis_client = await aioredis.from_url(
        f"redis://{REDIS_HOST}:{REDIS_PORT}",
        decode_responses=True
    )
    logger.info("Redis connected")

async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        logger.info("Redis closed")

# Publish event
async def publish_event(channel: str, data: dict):
    try:
        await redis_client.publish(channel, json.dumps(data))
        logger.info(f"Event published to {channel}")
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")

# Auth dependency
def get_current_user(authorization: Optional[str] = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided")

    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"],
                           issuer="fitsync-user-service", audience="fitsync-api")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_redis()
    yield
    await close_db()
    await close_redis()

# App initialization
app = FastAPI(
    title="FitSync Schedule Service",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "schedule-service",
        "timestamp": datetime.utcnow().isoformat()
    }

# AVAILABILITY ENDPOINTS

@app.post("/api/availability")
async def create_availability(
    availability: AvailabilityCreate,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)
    if user["role"] not in ["admin", "trainer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    trainer_id = user["id"] if user["role"] == "trainer" else availability.trainer_id if hasattr(availability, 'trainer_id') else user["id"]

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            """INSERT INTO availability (trainer_id, gym_id, day_of_week, start_time, end_time,
                                        is_recurring, specific_date, max_slots)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING *""",
            trainer_id, availability.gym_id, availability.day_of_week, availability.start_time,
            availability.end_time, availability.is_recurring, availability.specific_date, availability.max_slots
        )
        return {"success": True, "data": dict(result)}

@app.get("/api/availability/trainer/{trainer_id}")
async def get_trainer_availability(
    trainer_id: str,
    authorization: str = Header(None, alias="Authorization")
):
    get_current_user(authorization)

    async with db_pool.acquire() as conn:
        results = await conn.fetch(
            "SELECT * FROM availability WHERE trainer_id = $1 AND is_active = true ORDER BY day_of_week, start_time",
            trainer_id
        )
        return {"success": True, "data": [dict(r) for r in results]}

@app.delete("/api/availability/{availability_id}")
async def delete_availability(
    availability_id: str,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)
    if user["role"] not in ["admin", "trainer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async with db_pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE availability SET is_active = false WHERE id = $1",
            availability_id
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Availability not found")
        return {"success": True, "message": "Availability removed"}

# BOOKING ENDPOINTS

@app.post("/api/bookings")
async def create_booking(
    booking: BookingCreate,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)
    client_id = user["id"]

    # Validate trainer exists
    try:
        trainer_data = await validate_user(booking.trainer_id, authorization)
        if trainer_data["data"]["role"] != "trainer":
            raise HTTPException(status_code=400, detail="Specified user is not a trainer")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConnectionError:
        logger.warning("User service unavailable, skipping trainer validation")

    # Validate client has active program with trainer (optional check)
    try:
        programs = await get_active_programs(client_id, authorization)
        if programs["success"] and len(programs["data"]) > 0:
            has_program_with_trainer = any(
                p.get("trainer_id") == booking.trainer_id for p in programs["data"]
            )
            if not has_program_with_trainer:
                logger.warning(f"Client {client_id} booking with trainer {booking.trainer_id} without active program")
    except Exception as e:
        logger.warning(f"Could not verify active program: {e}")

    async with db_pool.acquire() as conn:
        # Check for conflicts
        conflict = await conn.fetchrow(
            """SELECT id FROM bookings
               WHERE trainer_id = $1 AND booking_date = $2
               AND status != 'cancelled'
               AND ((start_time, end_time) OVERLAPS ($3::time, $4::time))""",
            booking.trainer_id, booking.booking_date, booking.start_time, booking.end_time
        )

        if conflict:
            raise HTTPException(status_code=409, detail="Time slot already booked")

        result = await conn.fetchrow(
            """INSERT INTO bookings (type, trainer_id, client_id, gym_id, booking_date,
                                     start_time, end_time, notes)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING *""",
            booking.type.value, booking.trainer_id, client_id, booking.gym_id,
            booking.booking_date, booking.start_time, booking.end_time, booking.notes
        )

        # Publish event
        await publish_event("booking.created", {
            "booking_id": str(result["id"]),
            "client_id": client_id,
            "trainer_id": booking.trainer_id,
            "booking_date": booking.booking_date.isoformat(),
            "start_time": booking.start_time.isoformat(),
            "end_time": booking.end_time.isoformat(),
            "type": booking.type.value
        })

        return {"success": True, "data": dict(result)}

@app.get("/api/bookings")
async def list_bookings(
    status: Optional[BookingStatus] = None,
    page: int = 1,
    limit: int = 20,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)

    offset = (page - 1) * limit
    conditions = []
    params = []
    param_count = 1

    if user["role"] == "client":
        conditions.append(f"client_id = ${param_count}")
        params.append(user["id"])
        param_count += 1
    elif user["role"] == "trainer":
        conditions.append(f"trainer_id = ${param_count}")
        params.append(user["id"])
        param_count += 1

    if status:
        conditions.append(f"status = ${param_count}")
        params.append(status.value)
        param_count += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with db_pool.acquire() as conn:
        results = await conn.fetch(
            f"SELECT * FROM bookings {where_clause} ORDER BY booking_date DESC, start_time LIMIT ${param_count} OFFSET ${param_count + 1}",
            *params, limit, offset
        )
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM bookings {where_clause}",
            *params
        )

        return {
            "success": True,
            "data": [dict(r) for r in results],
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": count,
                "total_pages": (count + limit - 1) // limit
            }
        }

@app.get("/api/bookings/{booking_id}")
async def get_booking(
    booking_id: str,
    authorization: str = Header(None, alias="Authorization")
):
    get_current_user(authorization)

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            "SELECT * FROM bookings WHERE id = $1",
            booking_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Booking not found")
        return {"success": True, "data": dict(result)}

@app.put("/api/bookings/{booking_id}/cancel")
async def cancel_booking(
    booking_id: str,
    cancel: CancelBooking,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            """UPDATE bookings
               SET status = 'cancelled', cancelled_at = NOW(), cancellation_reason = $1
               WHERE id = $2
               RETURNING *""",
            cancel.cancellation_reason, booking_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Booking not found")

        # Publish event
        await publish_event("booking.cancelled", {
            "booking_id": booking_id,
            "client_id": str(result["client_id"]),
            "reason": cancel.cancellation_reason
        })

        return {"success": True, "data": dict(result)}

@app.put("/api/bookings/{booking_id}/complete")
async def complete_booking(
    booking_id: str,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)
    if user["role"] not in ["admin", "trainer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            "UPDATE bookings SET status = 'completed' WHERE id = $1 RETURNING *",
            booking_id
        )

        if not result:
            raise HTTPException(status_code=404, detail="Booking not found")

        # Calculate duration in minutes
        start_dt = datetime.combine(result["booking_date"], result["start_time"])
        end_dt = datetime.combine(result["booking_date"], result["end_time"])
        duration_minutes = int((end_dt - start_dt).total_seconds() / 60)

        # Publish booking completed event
        await publish_event("booking.completed", {
            "booking_id": str(result["id"]),
            "client_id": str(result["client_id"]),
            "trainer_id": str(result["trainer_id"]),
            "workout_date": result["booking_date"].isoformat(),
            "start_time": result["start_time"].isoformat(),
            "end_time": result["end_time"].isoformat(),
            "duration_minutes": duration_minutes,
            "trainer_notes": result.get("notes", "")
        })

        return {"success": True, "data": dict(result)}

# GROUP SESSION ENDPOINTS

@app.post("/api/sessions/group")
async def create_group_session(
    session: GroupSessionCreate,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)
    if user["role"] not in ["admin", "trainer"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            """INSERT INTO group_sessions (trainer_id, session_name, description, max_participants,
                                          gym_id, session_date, start_time, end_time)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING *""",
            session.trainer_id, session.session_name, session.description, session.max_participants,
            session.gym_id, session.session_date, session.start_time, session.end_time
        )
        return {"success": True, "data": dict(result)}

@app.get("/api/sessions/group")
async def list_group_sessions(
    page: int = 1,
    limit: int = 20,
    authorization: str = Header(None, alias="Authorization")
):
    get_current_user(authorization)

    offset = (page - 1) * limit

    async with db_pool.acquire() as conn:
        results = await conn.fetch(
            "SELECT * FROM group_sessions WHERE status = 'scheduled' ORDER BY session_date, start_time LIMIT $1 OFFSET $2",
            limit, offset
        )
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM group_sessions WHERE status = 'scheduled'"
        )

        return {
            "success": True,
            "data": [dict(r) for r in results],
            "pagination": {
                "page": page,
                "limit": limit,
                "total_count": count,
                "total_pages": (count + limit - 1) // limit
            }
        }

@app.post("/api/sessions/group/{session_id}/enroll")
async def enroll_in_group_session(
    session_id: str,
    authorization: str = Header(None, alias="Authorization")
):
    user = get_current_user(authorization)
    client_id = user["id"]

    async with db_pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT * FROM group_sessions WHERE id = $1",
            session_id
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        if session["current_participants"] >= session["max_participants"]:
            raise HTTPException(status_code=400, detail="Session is full")

        if client_id in session["enrolled_clients"]:
            raise HTTPException(status_code=400, detail="Already enrolled")

        result = await conn.fetchrow(
            """UPDATE group_sessions
               SET enrolled_clients = array_append(enrolled_clients, $1),
                   current_participants = current_participants + 1
               WHERE id = $2
               RETURNING *""",
            client_id, session_id
        )

        return {"success": True, "data": dict(result)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8003))
    uvicorn.run(app, host="0.0.0.0", port=port)
