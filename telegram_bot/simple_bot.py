"""
Simple Telegram Bot Test - Compatible with Python 3.13

First, let's test if we can get basic functionality working.
"""

import os
import sys
import logging
from pathlib import Path

# Add paths for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "packages"))

# Try to import telegram with better error handling
try:
    import telegram
    print(f"✅ Telegram library loaded: {telegram.__version__}")
except ImportError as e:
    print(f"❌ Error importing telegram: {e}")
    print("Try: pip install python-telegram-bot==20.7")
    sys.exit(1)

# Try to import core
try:
    from core import TradingCore
    print("✅ Core module loaded")
except ImportError as e:
    print(f"❌ Error importing core: {e}")
    sys.exit(1)

# Test basic bot functionality
async def simple_test():
    """Test basic bot functionality"""
    
    # Check for token
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN not found")
        print("Set it with: export TELEGRAM_BOT_TOKEN='your-token'")
        return
    
    if token == "your-telegram-bot-token-here":
        print("❌ Please set a real Telegram bot token in .env")
        return
    
    print(f"✅ Bot token found: ...{token[-10:]}")
    
    # Test core functionality
    try:
        # Test with mock config for now
        mock_config = {
            "API_KEY": "test",
            "API_SECRET": "test", 
            "PAPER": True
        }
        core = TradingCore(broker_config=mock_config)
        strategies = core.list_strategies()
        print(f"✅ Found {len(strategies)} strategies: {list(strategies.keys())}")
    except Exception as e:
        print(f"⚠️ Core test failed: {e}")
    
    # Test telegram bot creation
    try:
        from telegram.ext import Application
        app = Application.builder().token(token).build()
        print("✅ Telegram Application created successfully")
        
        # Test basic message
        print("🚀 Bot is ready! Testing complete.")
        
    except Exception as e:
        print(f"❌ Telegram application failed: {e}")
        print("This might be due to Python 3.13 compatibility issues")
        print("Try using Python 3.11 or 3.12 instead")

def main():
    """Main test function"""
    print("🧪 Testing Telegram Bot Setup")
    print("=" * 40)
    
    # Load .env if it exists
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ Loaded .env from {env_path}")
    except ImportError:
        print("⚠️ python-dotenv not installed")
    
    # Run async test
    import asyncio
    try:
        asyncio.run(simple_test())
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()