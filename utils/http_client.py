import httpx
import os
import logging

logger = logging.getLogger("schedule-service")

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://localhost:3001")
TRAINING_SERVICE_URL = os.getenv("TRAINING_SERVICE_URL", "http://localhost:3002")


async def validate_user(user_id: str, token: str):
    """Validate if a user exists and get their info"""
    try:
        # Token might already have "Bearer " prefix
        auth_header = token if token.startswith("Bearer ") else f"Bearer {token}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{USER_SERVICE_URL}/api/users/{user_id}",
                headers={"Authorization": auth_header},
                timeout=5.0
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"User {user_id} not found")
        raise
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.error(f"User service unavailable")
        raise ConnectionError("User service unavailable")


async def get_active_programs(client_id: str, token: str):
    """Get active programs for a client from Training Service"""
    try:
        # Token might already have "Bearer " prefix
        auth_header = token if token.startswith("Bearer ") else f"Bearer {token}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{TRAINING_SERVICE_URL}/api/programs/client/{client_id}/active",
                headers={"Authorization": auth_header},
                timeout=5.0
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError:
        return {"success": False, "data": []}
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.error("Training service unavailable")
        return {"success": False, "data": []}


async def fetch_users_batch(user_ids: list, token: str):
    """Fetch multiple users in batch"""
    try:
        # Token might already have "Bearer " prefix
        auth_header = token if token.startswith("Bearer ") else f"Bearer {token}"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{USER_SERVICE_URL}/api/users/batch",
                json={"user_ids": user_ids},
                headers={"Authorization": auth_header},
                timeout=5.0
            )
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error(f"Error fetching users batch: {e}")
        return {"success": False, "data": [], "count": 0}
