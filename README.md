# FitSync Schedule Service

Booking and scheduling service for training sessions in the FitSync application.

## Features

- Training session booking management
- Trainer availability management
- Session scheduling and calendar
- Booking confirmations and cancellations
- Time slot management
- Conflict detection

## Technology Stack

- Python 3.11+
- FastAPI web framework
- PostgreSQL database
- Redis for caching
- SQLAlchemy ORM

## Running the Full FitSync Application

This service is part of the FitSync multi-repository application. To run the complete application:

### Quick Start

1. **Clone all repositories:**

```bash
mkdir fitsync-app && cd fitsync-app

git clone https://github.com/FitSync-G13/fitsync-docker-compose.git
git clone https://github.com/FitSync-G13/fitsync-api-gateway.git
git clone https://github.com/FitSync-G13/fitsync-user-service.git
git clone https://github.com/FitSync-G13/fitsync-training-service.git
git clone https://github.com/FitSync-G13/fitsync-schedule-service.git
git clone https://github.com/FitSync-G13/fitsync-progress-service.git
git clone https://github.com/FitSync-G13/fitsync-notification-service.git
git clone https://github.com/FitSync-G13/fitsync-frontend.git
```

2. **Run setup:**

```bash
cd fitsync-docker-compose
./setup.sh    # Linux/Mac
setup.bat     # Windows
```

3. **Access:** http://localhost:3000

## Development - Run This Service Locally

1. **Start infrastructure:**
```bash
cd ../fitsync-docker-compose
docker compose up -d scheduledb redis user-service
docker compose stop schedule-service
```

2. **Install dependencies:**
```bash
cd ../fitsync-schedule-service
pip install -r requirements.txt
```

3. **Configure environment (.env):**
```env
ENVIRONMENT=development
PORT=8003
DB_HOST=localhost
DB_PORT=5434
DB_NAME=scheduledb
DB_USER=fitsync
DB_PASSWORD=fitsync123
REDIS_HOST=localhost
REDIS_PORT=6379
USER_SERVICE_URL=http://localhost:3001
JWT_SECRET=your-super-secret-jwt-key-change-in-production
```

4. **Run migrations:**
```bash
python -m alembic upgrade head
```

5. **Start development server:**
```bash
uvicorn app:app --reload --port 8003
```

Service runs on http://localhost:8003

## API Endpoints

- `GET /api/bookings` - Get all bookings
- `POST /api/bookings` - Create new booking
- `GET /api/bookings/:id` - Get booking details
- `PUT /api/bookings/:id` - Update booking
- `DELETE /api/bookings/:id` - Cancel booking
- `GET /api/availability` - Check trainer availability

## Database Schema

Main tables:
- `bookings`         - Training session bookings
- `availability`     - Trainer availability slots
- `sessions`         - Completed sessions

## More Information

See [fitsync-docker-compose](https://github.com/FitSync-G13/fitsync-docker-compose) for complete documentation.

## License

MIT
