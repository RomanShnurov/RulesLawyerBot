"""Load test script for concurrent users.

This is a manual test script for simulating concurrent users.
NOT meant to be run by pytest.

Usage:
    1. Set your TELEGRAM_TOKEN and CHAT_ID below
    2. Run: python tests/load_test.py
"""
import asyncio
import os
import time
from telegram import Bot


async def simulate_user(bot: Bot, chat_id: int, message: str):
    """Simulate single user request.

    Args:
        bot: Telegram bot instance
        chat_id: Chat ID to send message to
        message: Message text
    """
    start = time.time()
    await bot.send_message(chat_id=chat_id, text=message)
    duration = time.time() - start
    print(f"Request completed in {duration:.2f}s")


async def load_test(token: str, chat_id: int, num_users: int = 10):
    """Simulate multiple concurrent users.

    Args:
        token: Telegram bot token
        chat_id: Chat ID to send messages to
        num_users: Number of concurrent users to simulate
    """
    bot = Bot(token=token)

    tasks = [
        simulate_user(bot, chat_id, f"Test message {i}")
        for i in range(num_users)
    ]

    start = time.time()
    await asyncio.gather(*tasks)
    total = time.time() - start

    print(f"\n✅ {num_users} requests completed in {total:.2f}s")
    print(f"Average: {total/num_users:.2f}s per request")


# Run: python tests/load_test.py
if __name__ == "__main__":
    # Configuration - set these from environment or hardcode for testing
    TOKEN = os.getenv("TELEGRAM_TOKEN", "YOUR_TOKEN_HERE")
    CHAT_ID = int(os.getenv("TEST_CHAT_ID", "123456789"))
    NUM_USERS = int(os.getenv("NUM_USERS", "10"))

    if TOKEN == "YOUR_TOKEN_HERE":
        print("⚠️  ERROR: Please set TELEGRAM_TOKEN environment variable or edit the script")
        print("   Example: export TELEGRAM_TOKEN='your-token-here'")
        print("   Example: export TEST_CHAT_ID='your-chat-id'")
        exit(1)

    print(f"Starting load test with {NUM_USERS} concurrent users...")
    print(f"Target chat ID: {CHAT_ID}")
    print(f"Token: {TOKEN[:10]}...{TOKEN[-4:]}")
    print()

    asyncio.run(load_test(TOKEN, CHAT_ID, num_users=NUM_USERS))
