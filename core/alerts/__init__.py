"""
Intelligent Alert System for Stock Trading

This module provides an AI-powered alert system that:
- Filters noise from thousands of alerts
- Detects monthly growth trends
- Identifies buying opportunities during dips
- Prioritizes alerts as HOT/WATCH/IGNORE

Usage:
    from alerts.models.schemas import StockData, Opportunity
    from alerts.alert_system import AlertSystem
"""

# Lazy imports to avoid loading parent package dependencies
__all__ = [
    "StockData",
    "TechnicalIndicators",
    "TrendAnalysis",
    "DipInfo",
    "Opportunity",
    "Priority",
    "AlertSummary",
    "AlpacaDataService",
    "TelegramService",
    "TechnicalAnalyzer",
    "TrendAnalyzer",
    "DipDetector",
    "OpportunityScorer",
    "AlertSystem",
]
