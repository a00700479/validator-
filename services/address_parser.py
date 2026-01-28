"""Service for parsing input addresses from various sources."""
import ipaddress
from pathlib import Path
from typing import List, Tuple, Optional


class AddressParser:
    """Parse IP addresses from different input formats."""
    
    @staticmethod
    def parse_addresses(input_str: str) -> Tuple[List[str], Optional[str]]:
        """
        Parse addresses from input string (single, comma-separated, or file path).
        
        Args:
            input_str: Input string containing address(es) or file path
            
        Returns:
            Tuple of (list of addresses, error message if any)
        """
        # Check if it's a file path
        if Path(input_str).exists() and Path(input_str).is_file():
            return AddressParser._parse_from_file(input_str)
        
        # Try to parse as comma-separated list
        addresses = []
        parts = [p.strip() for p in input_str.split(',')]
        
        for part in parts:
            if not part:
                continue
            
            # Validate IP address
            if AddressParser._is_valid_ip(part):
                addresses.append(part)
            else:
                return [], f"Некорректный IP адрес: '{part}'"
        
        if not addresses:
            return [], "Не указано ни одного валидного IP адреса"
        
        return addresses, None
    
    @staticmethod
    def _parse_from_file(filepath: str) -> Tuple[List[str], Optional[str]]:
        """
        Parse addresses from file (one per line).
        
        Args:
            filepath: Path to file with addresses
            
        Returns:
            Tuple of (list of addresses, error message if any)
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            addresses = []
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                # Validate IP address
                if AddressParser._is_valid_ip(line):
                    addresses.append(line)
                else:
                    return [], f"Некорректный IP адрес в строке {line_num}: '{line}'"
            
            if not addresses:
                return [], f"Файл {filepath} не содержит валидных IP адресов"
            
            return addresses, None
            
        except UnicodeDecodeError:
            return [], f"Ошибка чтения файла {filepath}: неверная кодировка (ожидается UTF-8)"
        except Exception as e:
            return [], f"Ошибка чтения файла {filepath}: {str(e)}"
    
    @staticmethod
    def _is_valid_ip(address: str) -> bool:
        """Check if string is a valid IPv4 or IPv6 address."""
        try:
            ipaddress.ip_address(address)
            return True
        except ValueError:
            return False

