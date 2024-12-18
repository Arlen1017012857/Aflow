"""Weather API tool for testing

用于测试天气查询， This tool demonstrates API integration capabilities by providing weather information.

Category: api_tools
Tools: weather_api
"""

from typing import Dict
import requests

class WeatherAPI:
    """Weather API tool for testing
    
    This tool demonstrates API integration capabilities.
    """
    
    def __init__(self, api_key: str = None):
        """Initialize WeatherAPI tool
        
        Args:
            api_key: Optional API key for weather service
        """
        self.api_key = api_key
        self.base_url = "https://api.example.com/weather"
    
    def get_weather(self, city: str) -> Dict:
        """Get weather information for a city
        
        Args:
            city: Name of the city
            
        Returns:
            Dict containing weather information
            
        Note:
            This is a mock implementation for testing
        """
        params = {
            'city': city,
            'api_key': self.api_key
        }
        response = requests.get(self.base_url, params=params)
        return response.json()
    
    def get_forecast(self, city: str, days: int = 5) -> Dict:
        """Get weather forecast for a city
        
        Args:
            city: Name of the city
            days: Number of days to forecast (default: 5)
            
        Returns:
            Dict containing forecast information
            
        Note:
            This is a mock implementation for testing
        """
        # Mock response for testing
        return {
            "city": city,
            "forecast": [
                {
                    "day": i + 1,
                    "temperature": 20 + i,
                    "conditions": "sunny"
                }
                for i in range(days)
            ]
        }
