import subprocess
import re
import shutil
from typing import Optional
import pandas as pd
from tqdm import tqdm

from .base import DataFrameValidator
from config.columns import COLUMNS


class WhoisCountryValidator(DataFrameValidator):
    """Валидатор страны по Whois. Проверяет принадлежность IP адреса к России."""
    
    def __init__(self):
        self._whois_available: Optional[bool] = None
        self._warning_shown = False
        self.IP_PORT_COLUMN = COLUMNS[12].name
    
    @property
    def name(self) -> str:
        return "WHOIS"
    
    @property
    def description(self) -> str:
        return "Проверка страны (whois)"
    
    def is_available(self) -> bool:
        """Проверяет, доступна ли команда whois """
        if self._whois_available is None:
            self._whois_available = shutil.which("whois") is not None
        return self._whois_available
    
    def get_startup_warning(self) -> Optional[str]:
        """Get warning message if whois is not available."""
        if not self.is_available() and not self._warning_shown:
            self._warning_shown = True
            return (
                "⚠️  ВНИМАНИЕ: в системе отсутствует утилита whois. "
                "Проверка на принадлежность IP адреса конкретной стране будет пропущена."
            )
        return None
    
    def get_final_warning(self) -> Optional[str]:
        if not self.is_available():
            return (
                "⚠️  Проверка на принадлежность IP адреса конкретной стране не сработала, "
                "потому что в системе отсутствует whois."
            )
        return None
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        """Validate country for each IP using whois."""
        errors = self._empty_errors(df)
        
        if not self.is_available():
            return errors
        
        if self.IP_PORT_COLUMN not in df.columns:
            return errors
        
        def extract_ip(address: str) -> Optional[str]:
            if not address or address == "nan":
                return None
            address = address.strip()
            
            ipv6_bracket_match = re.match(r'^\[([0-9a-fA-F:]+)\]', address)
            if ipv6_bracket_match:
                return ipv6_bracket_match.group(1)
            
            ipv4_match = re.match(r'^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', address)
            if ipv4_match:
                return ipv4_match.group(1)
            
            ipv6_match = re.match(r'^([0-9a-fA-F:]+)', address)
            if ipv6_match:
                candidate = ipv6_match.group(1)
                if ':' in candidate:
                    return candidate
            
            return None
        
        addresses = df[self.IP_PORT_COLUMN].astype(str).str.strip()
        ips = addresses.apply(extract_ip)
        results = []
        unique_ips = ips.dropna().unique()

        cache = {}
        
        print(f"\n  🌍 Whois проверка {len(unique_ips)} уникальных IP...")
        for ip in tqdm(unique_ips, desc="  Whois запросы", leave=False, ncols=80):
            country = self._get_country_from_whois(ip)
            cache[ip] = country
            status = "✅" if country and country.upper() == "RU" else "❌"
            country_str = country if country else "N/A"
            tqdm.write(f"    {status} {ip} -> {country_str}")
        
        def check_country(ip: Optional[str]) -> str:
            if ip is None:
                return ""
            
            country = cache.get(ip)
            
            if country is None:
                return self._make_error(
                    f"Не удалось определить страну для IP: {ip}",
                    "Проверочный IP+Порт"
                )
            
            if country.upper() != "RU":
                return self._make_error(
                    f"IP {ip} принадлежит стране '{country}', ожидается 'RU'",
                    "Проверочный IP+Порт"
                )
            
            return ""
        
        errors = ips.apply(check_country)
        return errors
    
    def _get_country_from_whois(self, ip: str, timeout: int = 10) -> Optional[str]:
        """
        run whois command with -r option and return country code
        """
        try:
            result = subprocess.run(
                ["whois", "-r", ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                text=True
            )
            
            output = result.stdout
            
            # 1. Основная проверка на наличие страны в выводе whois
            match = re.search(r'country:\s*(\w{2})', output, re.IGNORECASE)
            if match:
                country = match.group(1).upper()
                if country == "RU":
                    return country
            
            # 2. Доп проверки на наличие России в выводе whois
            russia_patterns = [
                r'address:\s*.*Russian Federation',
                r'address:\s*.*Russia\b',
                r'address:\s*.*Россия',
                r'address:\s*.*РФ\b',
            ]
            for pattern in russia_patterns:
                if re.search(pattern, output, re.IGNORECASE):
                    return "RU"
            if match:
                return match.group(1).upper()
            
            return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
