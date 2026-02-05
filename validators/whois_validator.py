import subprocess
import re
import shutil
from typing import Optional

import pandas as pd
import sys

from .base import DataFrameValidator
from config.columns import COLUMNS



class WhoisCountryValidator(DataFrameValidator):
    """Валидатор страны по IP (RU) через  whois RDAP (ipwhois)"""

    def __init__(self):
        self._warning_shown = False
        self._mode_cached: Optional[str] = None  # "cli" | "rdap" | "none"
        self.IP_PORT_COLUMN = COLUMNS[12].name  # Проверочный IP+Порт

    @property
    def name(self) -> str:
        return "WHOIS"

    @property
    def description(self) -> str:
        return "Проверка страны (whois/rdap)"

    def _detect_mode(self) -> str:
        """Определяем, чем можем проверять:  ipwahois-rdap / whois-cli / никак"""
        if self._mode_cached:
            return self._mode_cached

        # 1) Сначала пробуем RDAP (на Windows это самый стабильный вариант)
        try:
            import ipwhois  # noqa: F401
            self._mode_cached = "rdap"
            return self._mode_cached
        except Exception:
            pass

        # 2) Потом whois-cli (если реально установлен)
        if shutil.which("whois"):
            self._mode_cached = "cli"
            return self._mode_cached
        
        # 3) иначе никак
        self._mode_cached = "none"
        return self._mode_cached 

    def is_available(self) -> bool:
        return self._detect_mode() != "none"

    def get_startup_warning(self) -> Optional[str]:
        mode = self._detect_mode()
        if mode == "none" and not self._warning_shown:
            self._warning_shown = True
            return (
                "⚠️  ВНИМАНИЕ: в системе нет whois (CLI) и не установлен ipwhois. \n"
                "Проверка страны для IP будет пропущена. \n"
                "Установите: pip install ipwhois"
            )
        return None

    def get_final_warning(self) -> Optional[str]:
        mode = self._detect_mode()
        if mode == "none":
            return "⚠️  Проверка страны для IP адреса не выполнялась: нет whois (CLI) и ipwhois."
        return None

    def validate(self, df: pd.DataFrame) -> pd.Series:
        """Validate country for each IP using whois."""
        errors = self._empty_errors(df)

        mode = self._detect_mode()
        if mode == "none":
            return errors

        if self.IP_PORT_COLUMN not in df.columns:
            return errors

        def extract_ip(address: str) -> Optional[str]:
            if not address or str(address).strip().lower() == "nan":
                return None
            address = str(address).strip()

            # [IPv6]:port
            m = re.match(r"^\[([0-9a-fA-F:]+)\]", address)
            if m:
                return m.group(1)

            # IPv4[:port]
            m = re.match(r"^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", address)
            if m:
                return m.group(1)

            # IPv6 (без скобок)
            m = re.match(r"^([0-9a-fA-F:]+)", address)
            if m and ":" in m.group(1):
                return m.group(1)
                
            return None

        ips = df[self.IP_PORT_COLUMN].astype(str).str.strip().apply(extract_ip)
        unique_ips = ips.dropna().unique()

        cache: dict[str, Optional[str]] = {}
        print(f"\n  🌍 Whois/RDAP проверка {len(unique_ips)} уникальных IP...")
        
        for ip in unique_ips:
            country = self._get_country(ip, mode=mode)
            cache[ip] = country

            if sys.stdout.isatty():
                status = "OK" if country and country.upper() == "RU" else "❌"
                country_str = country if country else "N/A"
                print (f"    {status} {ip} -> {country_str}")
  
           
        def check_country(ip: Optional[str]) -> str:
            if ip is None:
                return ""
            
            country = cache.get(ip)

            if country is None:
                return self._make_error(
                    f"Не удалось определить страну для IP: {ip}",
                    self.IP_PORT_COLUMN
                )
            
            if country == "PRIVATE":
                return "" # не считаем ошибкой

            if country.upper() != "RU":
                return self._make_error(
                    f"IP {ip} принадлежит стране '{country}', ожидается 'RU'",
                    self.IP_PORT_COLUMN
                )

            return ""

        return ips.apply(check_country)

        
    def _get_country(self, ip: str, mode: str, timeout: int = 10) -> Optional[str]:
        """
        Возвращает код страны (например RU/US) или None
        """
        if mode == "cli":
            return self._get_country_from_whois_cli(ip, timeout=timeout)
        if mode == "rdap":
            return self._get_country_from_rdap(ip, timeout=timeout)
        return None

    def _get_country_from_rdap(self, ip: str, timeout: int = 10) -> Optional[str]:
        try:
            from ipwhois import IPWhois
            from ipwhois.exceptions import IPDefinedError

            try: 
                obj = IPWhois(ip, timeout=timeout)

                # 1) RDAP (быстро)
                rdap = obj.lookup_rdap()
                net = rdap.get("network") or {}
                net_cc = (net.get("country") or "").strip()
                if net_cc:
                    return str(net_cc).upper()

                # 2) fallback: WHOIS parsing (чаще совпадает с RIPE "country:")
                who = obj.lookup_whois()
                nets = who.get("nets") or []
                for n in nets:
                    cc = (n.get("country") or "").strip()
                    if cc:
                        return cc.upper()

                return None

            except IPDefinedError:
                return "PRIVATE"

        except Exception:
            return None         

    def _get_country_from_whois_cli(self, ip: str, timeout: int = 10) -> Optional[str]:
        try:
            result = subprocess.run(
                ["whois", "-r", ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                text=True,
            )

            output = result.stdout or ""

            # 1. Основная проверка на наличие страны в выводе whois
            m = re.search(r"country:\s*(\w{2})", output, re.IGNORECASE)
            if m:
                return m.group(1).upper()
            return None
        except Exception:
            return None

            
        
            

            

    
        

