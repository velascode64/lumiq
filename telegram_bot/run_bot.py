#!/usr/bin/env python3
"""
Script to run the Telegram Trading Bot

This script properly handles imports and environment setup
for running the bot from any directory.
"""

import os
import sys
from pathlib import Path

# Add parent directories to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "packages"))

# Load environment variables
from dotenv import load_dotenv
env_path = Path(__file__).parent / '.env'
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ Loaded .env from {env_path}")
else:
    print(f"⚠️  No .env file found at {env_path}")
    print("Make sure TELEGRAM_BOT_TOKEN is set in environment variables")

# Also load core .env if present (for Alpaca + alerts config)
core_env = project_root / "packages" / "core" / ".env"
if core_env.exists():
    load_dotenv(core_env)
    print(f"✅ Loaded .env from {core_env}")

# Import and run the bot
from telegram.telegram_bot import main

if __name__ == "__main__":
    print("🚀 Starting Telegram Trading Bot...")
    print("=" * 50)
    
    # Check for required environment variables
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("❌ Error: TELEGRAM_BOT_TOKEN not found!")
        print("\nPlease set it either:")
        print("1. In a .env file (copy .env.example to .env)")
        print("2. As an environment variable:")
        print("   export TELEGRAM_BOT_TOKEN='your-bot-token'")
        sys.exit(1)
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
