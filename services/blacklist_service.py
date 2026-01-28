"""Blacklist configuration service."""
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class BlacklistService:
    """Service for loading and managing blacklist configuration."""
    
    def load_blacklist(self, filepath: str) -> Tuple[Dict[str, List[str]], Optional[str]]:
        """
        Load blacklist from JSON file.
        
        Expected format:
        {
            "source_name": ["10.0.0.0/8", "192.168.0.0/16"],
            "another_source": ["172.16.0.0/12"]
        }
        
        Args:
            filepath: Path to JSON file
            
        Returns:
            Tuple of (blacklist_dict, error_message)
        """
        try:
            # Check file exists
            if not Path(filepath).exists():
                return {}, f"Файл blacklist не найден: {filepath}"
            
            # Read and parse JSON
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Validate structure
            if not isinstance(data, dict):
                return {}, "Blacklist должен быть словарём"
            
            for source_name, subnets in data.items():
                if not isinstance(subnets, list):
                    return {}, f"Значение для '{source_name}' должно быть списком подсетей"
                
                for subnet in subnets:
                    if not isinstance(subnet, str):
                        return {}, f"Подсеть должна быть строкой: {subnet}"
                    
                    # Basic validation of subnet format
                    if "/" not in subnet:
                        return {}, f"Некорректный формат подсети (отсутствует маска): {subnet}"
            
            return data, None
            
        except json.JSONDecodeError as e:
            return {}, f"Ошибка парсинга JSON: {str(e)}"
        except Exception as e:
            return {}, f"Ошибка загрузки blacklist: {str(e)}"

