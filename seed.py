import asyncio
import asyncpg
from datetime import datetime, timedelta, time
import os
from dotenv import load_dotenv

load_dotenv()

# Test user IDs from user service
TRAINER_ID = '4420f58b-f7b9-415c-afcb-60d23ae6c17f'  # trainer@fitsync.com
CLIENT_ID = 'ae34ea3f-fea2-42bb-b7bc-8337e4f187f5'   # client@fitsync.com
GYM_ID = '65710aef-2ba3-49d1-a4e1-f422dee801d1'      # FitSync Downtown

async def seed_data():
    """Seed schedule service with test data"""
    conn = await asyncpg.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', 5434)),
        user=os.getenv('DB_USER', 'fitsync'),
        password=os.getenv('DB_PASSWORD', 'fitsync123'),
        database=os.getenv('DB_NAME', 'scheduledb')
    )

    try:
        # Create trainer availability for next 2 weeks
        print("Creating trainer availability...")
        availability_count = 0

        for day_offset in range(14):
            date = datetime.now().date() + timedelta(days=day_offset)
            # Skip weekends
            if date.weekday() >= 5:
                continue

            # Morning slots (9 AM - 12 PM)
            for hour in [9, 10, 11]:
                try:
                    await conn.execute("""
                        INSERT INTO availability (trainer_id, available_date, start_time, end_time, is_booked)
                        VALUES ($1, $2, $3, $4, false)
                    """, TRAINER_ID, date, time(hour, 0, 0), time(hour+1, 0, 0))
                    availability_count += 1
                except Exception as e:
                    print(f"Availability slot already exists: {date} {hour}:00")

            # Afternoon slots (2 PM - 5 PM)
            for hour in [14, 15, 16]:
                try:
                    await conn.execute("""
                        INSERT INTO availability (trainer_id, available_date, start_time, end_time, is_booked)
                        VALUES ($1, $2, $3, $4, false)
                    """, TRAINER_ID, date, time(hour, 0, 0), time(hour+1, 0, 0))
                    availability_count += 1
                except Exception as e:
                    print(f"Availability slot already exists: {date} {hour}:00")

        print(f"Created {availability_count} availability slots")

        # Create some bookings for the test client
        print("Creating bookings...")
        booking_count = 0

        # Past completed booking (1 week ago)
        past_date = datetime.now().date() - timedelta(days=7)
        try:
            await conn.execute("""
                INSERT INTO bookings (client_id, trainer_id, booking_date, start_time, end_time, type, status, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, CLIENT_ID, TRAINER_ID, past_date, time(10, 0, 0), time(11, 0, 0),
                 "one_on_one", "completed", "Great workout session!")
            booking_count += 1
        except Exception as e:
            print(f"Past booking already exists: {e}")

        # Upcoming booking (tomorrow)
        tomorrow = datetime.now().date() + timedelta(days=1)
        try:
            await conn.execute("""
                INSERT INTO bookings (client_id, trainer_id, booking_date, start_time, end_time, type, status, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, CLIENT_ID, TRAINER_ID, tomorrow, time(10, 0, 0), time(11, 0, 0),
                 "one_on_one", "scheduled", "Upper body focus")
            booking_count += 1
        except Exception as e:
            print(f"Tomorrow booking already exists: {e}")

        # Another upcoming booking (3 days from now)
        future_date = datetime.now().date() + timedelta(days=3)
        try:
            await conn.execute("""
                INSERT INTO bookings (client_id, trainer_id, booking_date, start_time, end_time, type, status, notes)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, CLIENT_ID, TRAINER_ID, future_date, time(15, 0, 0), time(16, 0, 0),
                 "one_on_one", "scheduled", "Leg day")
            booking_count += 1
        except Exception as e:
            print(f"Future booking already exists: {e}")

        print(f"Created {booking_count} bookings")

        # Create a group session
        print("Creating group session...")
        group_date = datetime.now().date() + timedelta(days=5)
        try:
            session_id = await conn.fetchval("""
                INSERT INTO group_sessions
                (trainer_id, session_name, description, session_date, start_time, end_time,
                 max_participants, current_participants, status, gym_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
            """, TRAINER_ID, "HIIT Bootcamp", "High intensity interval training for all levels",
                 group_date, time(18, 0, 0), time(19, 0, 0), 15, 1, "scheduled", GYM_ID)

            # Enroll the test client
            await conn.execute("""
                INSERT INTO session_enrollments (session_id, client_id, enrollment_status)
                VALUES ($1, $2, $3)
            """, session_id, CLIENT_ID, "confirmed")

            print(f"Created 1 group session with client enrolled")
        except Exception as e:
            print(f"Group session already exists: {e}")

        print("✅ Schedule service seed completed successfully!")

    except Exception as e:
        print(f"❌ Seed failed: {e}")
        raise
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(seed_data())
