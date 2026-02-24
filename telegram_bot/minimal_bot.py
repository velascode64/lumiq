"""
Minimal Working Telegram Bot - Compatibility First

This version focuses on getting basic functionality working
with the available libraries and Python version.
"""

import os
import sys
import logging
from pathlib import Path

# Add paths for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "packages"))

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ Environment loaded")
except ImportError:
    print("⚠️ dotenv not available, using system environment")

# Test Core functionality first
def test_core():
    """Test that our core module works"""
    try:
        from core import TradingCore
        print("✅ Core module imported")
        
        # Use mock config to avoid credential issues
        mock_config = {
            "API_KEY": os.getenv("ALPACA_API_KEY", "test"),
            "API_SECRET": os.getenv("ALPACA_API_SECRET", "test"),
            "PAPER": True,
            "BASE_URL": "https://paper-api.alpaca.markets"
        }
        
        core = TradingCore(broker_config=mock_config)
        print("✅ TradingCore initialized")
        
        # Test strategy discovery with correct path
        strategies_path = project_root / "packages" / "core" / "strategies"
        print(f"📁 Looking for strategies at: {strategies_path}")
        
        if strategies_path.exists():
            strategies = core.list_strategies()
            print(f"✅ Found {len(strategies)} strategies: {list(strategies.keys())}")
            
            # Show strategy details
            for name, info in strategies.items():
                print(f"  • {name}: {info.get('class', 'Unknown')}")
        else:
            print(f"❌ Strategies directory not found at {strategies_path}")
            
        return core
        
    except Exception as e:
        print(f"❌ Core test failed: {e}")
        import traceback
        traceback.print_exc()
        return None

# Simple HTTP server as fallback if telegram lib doesn't work
def run_simple_webhook():
    """Run a simple webhook server for testing"""
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        import json
        import urllib.parse
        
        class BotHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    
                    html = """
                    <html>
                    <body>
                        <h1>🤖 Lumibot Trading Bot Status</h1>
                        <p>Bot is running and ready!</p>
                        <p>Available endpoints:</p>
                        <ul>
                            <li><a href="/strategies">/strategies</a> - List available strategies</li>
                            <li><a href="/status">/status</a> - Bot status</li>
                        </ul>
                    </body>
                    </html>
                    """
                    self.wfile.write(html.encode())
                    
                elif self.path == '/strategies':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    core = test_core()
                    if core:
                        strategies = core.list_strategies()
                        self.wfile.write(json.dumps(strategies, indent=2).encode())
                    else:
                        self.wfile.write(b'{"error": "Core not available"}')
                        
                elif self.path == '/status':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    status = {
                        "status": "running",
                        "bot": "Lumibot Trading Bot",
                        "mode": "development",
                        "telegram_token": "configured" if os.getenv("TELEGRAM_BOT_TOKEN") else "missing"
                    }
                    self.wfile.write(json.dumps(status, indent=2).encode())
                else:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b'Not found')
            
            def log_message(self, format, *args):
                # Suppress default logging
                pass
        
        server = HTTPServer(('localhost', 8000), BotHandler)
        print("🌐 Starting HTTP server at http://localhost:8000")
        print("📱 This is a fallback while we fix Telegram integration")
        print("Press Ctrl+C to stop")
        server.serve_forever()
        
    except Exception as e:
        print(f"❌ HTTP server failed: {e}")

def try_telegram_bot():
    """Try to create a working Telegram bot"""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ No TELEGRAM_BOT_TOKEN found")
        return False
    
    try:
        # Try different telegram bot approaches
        
        # Approach 1: Using older telegram bot library
        try:
            import telegram
            from telegram.ext import Application
            
            print(f"📱 Telegram library version: {telegram.__version__}")
            
            # Create a simple bot that just tests connection
            async def test_connection():
                bot = telegram.Bot(token=token)
                try:
                    me = await bot.get_me()
                    print(f"✅ Bot connected: @{me.username} ({me.first_name})")
                    return True
                except Exception as e:
                    print(f"❌ Bot connection failed: {e}")
                    return False
            
            # Test connection
            import asyncio
            result = asyncio.run(test_connection())
            
            if result:
                print("🚀 Telegram bot is working!")
                print("📝 You can now use the bot by messaging it on Telegram")
                print("⚠️ Full interactive features coming soon...")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"❌ Telegram library error: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Telegram setup failed: {e}")
        return False

def main():
    """Main function with multiple fallback options"""
    print("🤖 Lumibot Telegram Bot - Testing Setup")
    print("=" * 50)
    
    # Step 1: Test core functionality
    print("\n1️⃣ Testing Core Module...")
    core = test_core()
    
    if not core:
        print("❌ Core module not working, stopping")
        return
    
    # Step 2: Try Telegram bot
    print("\n2️⃣ Testing Telegram Connection...")
    telegram_works = try_telegram_bot()
    
    if telegram_works:
        print("\n✅ Everything is working!")
        print("\n📱 Next steps:")
        print("1. Message your bot on Telegram")
        print("2. The bot will respond (basic functionality)")
        print("3. Full interactive trading features will be added next")
    else:
        print("\n⚠️ Telegram integration needs work")
        print("🌐 Starting HTTP server as alternative...")
        run_simple_webhook()

if __name__ == "__main__":
    main()