"""DataFrame-based validators using vectorized pandas operations."""
import re
import ipaddress
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from config.columns import (
    COLUMNS,
    VALID_IP_VERSIONS,
    VALID_CDN_VALUES,
    VALID_PROTOCOLS,
    VALID_CHECK_METHODS,
    REQUIRED_COLUMNS,
)
from .base import DataFrameValidator


# =============================================================================
# CONFIGURATION: Allowed separators for multi-value fields
# =============================================================================
ALLOWED_SEPARATORS = {
    "protocol": [",", "+", "/", " "],   # tcp,udp  tcp+udp  tcp/udp  tcp udp
    "method": [",", "+", "/", " "],     # ping,curl  ping+curl  etc.
}

def split_by_separators(value: str, field: str) -> List[str]:
    """Split value by allowed separators for the given field."""
    separators = ALLOWED_SEPARATORS.get(field, [","])
    # Build regex pattern: split by any of the separators
    pattern = "|".join(re.escape(sep) for sep in separators)
    parts = re.split(pattern, value)
    return [p.strip() for p in parts if p.strip()]


class RequiredFieldsValidator(DataFrameValidator):
    """Validates that all required fields are filled."""
    
    @property
    def name(self) -> str:
        return "REQUIRED"
    
    @property
    def description(self) -> str:
        return "Проверка обязательных полей"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        required_cols = {col.name for col in REQUIRED_COLUMNS}
        
        for col_name in required_cols:
            if col_name not in df.columns:
                continue
            
            # Check for empty/null values
            mask = df[col_name].isna() | (df[col_name].astype(str).str.strip() == "")
            
            error_msg = self._make_error("Обязательное поле не заполнено", col_name)
            errors = errors.where(~mask, errors + error_msg + "; ")
        
        return errors.str.rstrip("; ")


class UniqueNumberValidator(DataFrameValidator):
    """Validates that Number field is unique."""
    
    @property
    def name(self) -> str:
        return "UNIQUE"
    
    @property
    def description(self) -> str:
        return "Проверка уникальности Number"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "Number" not in df.columns:
            return errors
        
        # Find duplicates (keep first occurrence as valid)
        duplicated = df["Number"].duplicated(keep="first")
        
        error_msg = self._make_error("Дублирующийся номер", "Number")
        errors = errors.where(~duplicated, error_msg)
        
        return errors


class OgrnValidator(DataFrameValidator):
    """Validates ОГРН format (13 digits)."""
    
    @property
    def name(self) -> str:
        return "OGRN"
    
    @property
    def description(self) -> str:
        return "Проверка формата ОГРН"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "ОГРН" not in df.columns:
            return errors
        
        def validate_ogrn(val: str) -> str:
            if not val or val == "nan":
                return ""
            
            val = val.strip()
            
            # ОГРН должен быть строкой из ровно 13 цифр
            if re.match(r"^\d{13}$", val):
                return ""
            
            # Определяем длину для более информативной ошибки
            digit_count = len(val) if val.isdigit() else len(re.sub(r'\D', '', val))
            
            if digit_count > 0:
                return self._make_error(
                    f"ОГРН должен содержать 13 цифр, получено {digit_count}: '{val}'",
                    "ОГРН"
                )
            else:
                return self._make_error(
                    f"ОГРН должен содержать 13 цифр: '{val}'",
                    "ОГРН"
                )
        
        ogrn = df["ОГРН"].astype(str).str.strip()
        errors = ogrn.apply(validate_ogrn)
        
        return errors


class IpVersionValidator(DataFrameValidator):
    """Validates IP version field (v4 or v6)."""
    
    @property
    def name(self) -> str:
        return "IP_VERSION"
    
    @property
    def description(self) -> str:
        return "Проверка версии IP"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "IPv4/IPv6" not in df.columns:
            return errors
        
        version = df["IPv4/IPv6"].astype(str).str.strip().str.lower()
        not_empty = version != ""
        
        valid = version.isin(VALID_IP_VERSIONS)
        invalid = not_empty & ~valid
        
        error_msg = self._make_error(f"Допустимые значения: {VALID_IP_VERSIONS}", "IPv4/IPv6")
        errors = errors.where(~invalid, error_msg)
        
        return errors


class MaskFormatValidator(DataFrameValidator):
    """Validates mask format (/XX)."""
    
    @property
    def name(self) -> str:
        return "MASK"
    
    @property
    def description(self) -> str:
        return "Проверка формата маски"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "MASK" not in df.columns:
            return errors
        
        mask = df["MASK"].astype(str).str.strip()
        not_empty = mask != ""
        
        # Must start with /
        starts_with_slash = mask.str.startswith("/")
        invalid_start = not_empty & ~starts_with_slash
        
        error_msg1 = self._make_error("Маска должна начинаться с '/'", "MASK")
        errors = errors.where(~invalid_start, error_msg1)
        
        # Check format /XX
        valid_format = mask.str.match(r"^/\d+$", na=False)
        invalid_format = not_empty & starts_with_slash & ~valid_format
        
        error_msg2 = self._make_error("Маска должна быть в формате /XX", "MASK")
        errors = errors.where(~invalid_format, errors + "; " + error_msg2)
        
        return errors.str.lstrip("; ")


class PortFormatValidator(DataFrameValidator):
    """Validates port format (number, range, or list)."""
    
    @property
    def name(self) -> str:
        return "PORT"
    
    @property
    def description(self) -> str:
        return "Проверка формата порта"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "Port" not in df.columns:
            return errors
        
        port = df["Port"].astype(str).str.strip()
        not_empty = (port != "") & (port != "nan")
        
        def validate_port_value(val: str) -> str:
            if not val or val == "nan":
                return ""
            
            # Handle comma-separated list
            if "," in val:
                parts = [p.strip() for p in val.split(",")]
                for part in parts:
                    err = self._validate_single_port_or_range(part)
                    if err:
                        return self._make_error(f"Некорректный порт в списке: '{part}'", "Port")
                return ""
            
            # Handle range
            if "-" in val:
                err = self._validate_range(val)
                if err:
                    return self._make_error(f"Некорректный диапазон: '{val}'", "Port")
                return ""
            
            # Single port
            if not self._is_valid_port(val):
                return self._make_error(f"Некорректный порт: '{val}'", "Port")
            
            return ""
        
        errors = port.apply(validate_port_value)
        return errors
    
    def _is_valid_port(self, val: str) -> bool:
        try:
            p = int(val)
            return 1 <= p <= 65535
        except ValueError:
            return False
    
    def _validate_range(self, val: str) -> Optional[str]:
        parts = val.split("-")
        if len(parts) != 2:
            return "invalid"
        try:
            start, end = int(parts[0].strip()), int(parts[1].strip())
            if 1 <= start <= 65535 and 1 <= end <= 65535 and start <= end:
                return None
            return "invalid"
        except ValueError:
            return "invalid"
    
    def _validate_single_port_or_range(self, val: str) -> Optional[str]:
        if "-" in val:
            return self._validate_range(val)
        return None if self._is_valid_port(val) else "invalid"


class CdnValidator(DataFrameValidator):
    """Validates CDN field (yes or no)."""
    
    @property
    def name(self) -> str:
        return "CDN"
    
    @property
    def description(self) -> str:
        return "Проверка поля CDN"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "CDN Yes/No" not in df.columns:
            return errors
        
        cdn = df["CDN Yes/No"].astype(str).str.strip().str.lower()
        not_empty = cdn != ""
        
        valid = cdn.isin(VALID_CDN_VALUES)
        invalid = not_empty & ~valid
        
        error_msg = self._make_error(f"Допустимые значения: {VALID_CDN_VALUES}", "CDN Yes/No")
        errors = errors.where(~invalid, error_msg)
        
        return errors


class ProtocolValidator(DataFrameValidator):
    """Validates Protocol field (tcp, udp or comma-separated list)."""
    
    @property
    def name(self) -> str:
        return "PROTOCOL"
    
    @property
    def description(self) -> str:
        return "Проверка протокола"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "Protocol" not in df.columns:
            return errors
        
        def validate_protocols(val: str) -> str:
            if not val or val == "nan":
                return ""
            
            # Split by allowed separators, convert to lowercase
            parts = split_by_separators(val.lower(), "protocol")
            protocols = set(parts)
            
            # Check if all protocols are valid (subset of VALID_PROTOCOLS)
            invalid_protocols = protocols - VALID_PROTOCOLS
            
            if invalid_protocols:
                return self._make_error(
                    f"Недопустимые протоколы: {invalid_protocols}. Допустимые: {VALID_PROTOCOLS}",
                    "Protocol"
                )
            return ""
        
        protocol_col = df["Protocol"].astype(str).str.strip()
        errors = protocol_col.apply(validate_protocols)
        
        return errors


class MethodValidator(DataFrameValidator):
    """Validates check method field."""
    
    @property
    def name(self) -> str:
        return "METHOD"
    
    @property
    def description(self) -> str:
        return "Проверка способа проверки"
    
    # Cyrillic to Latin mapping for common lookalikes
    CYRILLIC_TO_LATIN = str.maketrans({
        'а': 'a', 'с': 'c', 'е': 'e', 'о': 'o', 'р': 'p', 
        'х': 'x', 'у': 'y', 'А': 'A', 'В': 'B', 'С': 'C',
        'Е': 'E', 'Н': 'H', 'К': 'K', 'М': 'M', 'О': 'O',
        'Р': 'P', 'Т': 'T', 'Х': 'X',
    })
    
    def _normalize_cyrillic(self, text: str) -> str:
        """Replace Cyrillic lookalike chars with Latin equivalents."""
        return text.translate(self.CYRILLIC_TO_LATIN)
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if "Способ проверки" not in df.columns:
            return errors
        
        def validate_methods(val: str) -> str:
            if not val or val == "nan":
                return ""
            
            # Split by allowed separators, normalize cyrillic, convert to lowercase
            parts = split_by_separators(val.lower(), "method")
            methods = {self._normalize_cyrillic(m) for m in parts}
            # Remove empty strings
            methods.discard("")
            
            # Check if all methods are valid (subset of VALID_CHECK_METHODS)
            invalid_methods = methods - VALID_CHECK_METHODS
            
            if invalid_methods:
                return self._make_error(
                    f"Недопустимые способы: {invalid_methods}. Допустимые: {VALID_CHECK_METHODS}",
                    "Способ проверки"
                )
            return ""
        
        method_col = df["Способ проверки"].astype(str).str.strip()
        errors = method_col.apply(validate_methods)
        
        return errors


class NetworkFormatValidator(DataFrameValidator):
    """Validates network field contains valid IP without mask."""
    
    def __init__(self):
        self.NETWORK_COLUMN = COLUMNS[5].name  # "Сеть в формате network ID"
    
    @property
    def name(self) -> str:
        return "NETWORK"
    
    @property
    def description(self) -> str:
        return "Проверка формата сети"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if self.NETWORK_COLUMN not in df.columns:
            return errors
        
        network = df[self.NETWORK_COLUMN].astype(str).str.strip()
        ip_version = df["IPv4/IPv6"].astype(str).str.strip().str.lower() if "IPv4/IPv6" in df.columns else pd.Series("", index=df.index)
        not_empty = network != ""
        
        # Check for mask in network field
        has_mask = network.str.contains("/", na=False)
        invalid_mask = not_empty & has_mask
        
        error_msg = self._make_error("Поле сети не должно содержать маску", self.NETWORK_COLUMN)
        errors = errors.where(~invalid_mask, error_msg)
        
        # Validate IP format
        def check_ip(row_data):
            net, ver = row_data
            if not net or net == "nan" or "/" in net:
                return ""
            
            try:
                if ver == "v4":
                    ipaddress.IPv4Address(net)
                elif ver == "v6":
                    ipaddress.IPv6Address(net)
                else:
                    # Try both
                    try:
                        ipaddress.IPv4Address(net)
                    except:
                        ipaddress.IPv6Address(net)
                return ""
            except:
                return self._make_error(f"Некорректный IP адрес: '{net}'", self.NETWORK_COLUMN)
        
        ip_errors = pd.DataFrame({"net": network, "ver": ip_version}).apply(
            lambda row: check_ip((row["net"], row["ver"])), axis=1
        )
        
        # Combine errors
        combined = errors.str.cat(ip_errors, sep="; ", na_rep="")
        return combined.str.strip("; ")


class HostBitsValidator(DataFrameValidator):
    """Validates that network address has no host bits set."""
    
    def __init__(self):
        self.NETWORK_COLUMN = COLUMNS[5].name  # "Сеть в формате network ID"
    
    @property
    def name(self) -> str:
        return "HOST_BITS"
    
    @property
    def description(self) -> str:
        return "Проверка host bits"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if self.NETWORK_COLUMN not in df.columns or "MASK" not in df.columns:
            return errors
        
        def check_host_bits(row):
            network = str(row.get(self.NETWORK_COLUMN, "")).strip()
            mask = str(row.get("MASK", "")).strip()
            ip_ver = str(row.get("IPv4/IPv6", "v4")).strip().lower()
            
            if not network or network == "nan" or not mask or mask == "nan":
                return ""
            
            if "/" in network:  # Already has error from NetworkFormatValidator
                return ""
            
            # Extract mask bits
            if mask.startswith("/"):
                mask = mask[1:]
            
            try:
                mask_bits = int(mask)
            except ValueError:
                return ""  # Mask format error handled by MaskFormatValidator
            
            try:
                network_str = f"{network}/{mask_bits}"
                if ip_ver == "v4":
                    ipaddress.IPv4Network(network_str, strict=True)
                else:
                    ipaddress.IPv6Network(network_str, strict=True)
                return ""
            except ValueError as e:
                if "has host bits set" in str(e).lower():
                    try:
                        if ip_ver == "v4":
                            net = ipaddress.IPv4Network(network_str, strict=False)
                        else:
                            net = ipaddress.IPv6Network(network_str, strict=False)
                        return self._make_error(
                            f"Указан IP-адрес хоста вместо адреса сети. "
                            f"Для маски {mask_bits} ожидается: {net.network_address}",
                            self.NETWORK_COLUMN
                        )
                    except:
                        pass
                return self._make_error(f"Ошибка валидации сети: {e}", self.NETWORK_COLUMN)
        
        errors = df.apply(check_host_bits, axis=1)
        return errors


class CheckIpPortFormatValidator(DataFrameValidator):
    """Validates check IP+Port format."""
    
    def __init__(self):
        self.IP_PORT_COLUMN = COLUMNS[12].name  # "Проверочный IP+Порт"
    
    @property
    def name(self) -> str:
        return "CHECK_IP_PORT"
    
    @property
    def description(self) -> str:
        return "Проверка формата IP+Порт"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if self.IP_PORT_COLUMN not in df.columns:
            return errors
        
        def check_format(row):
            address = str(row.get(self.IP_PORT_COLUMN, "")).strip()
            ip_ver = str(row.get("IPv4/IPv6", "")).strip().lower()
            
            if not address or address == "nan":
                return ""
            
            # 1. Check IPv6 format: [ip]:port
            ipv6_bracket_match = re.match(r'^\[([0-9a-fA-F:]+)\]:(\d+)$', address)
            if ipv6_bracket_match:
                ip, port = ipv6_bracket_match.group(1), int(ipv6_bracket_match.group(2))
                try:
                    ipaddress.IPv6Address(ip)
                    if ip_ver == "v4":
                        return self._make_error(
                            f"Указана версия v4, но адрес IPv6: '{address}'",
                            self.IP_PORT_COLUMN
                        )
                    if not (1 <= port <= 65535):
                        return self._make_error(f"Порт вне диапазона: {port}", self.IP_PORT_COLUMN)
                    return ""
                except:
                    return self._make_error(f"Некорректный IPv6: '{ip}'", self.IP_PORT_COLUMN)
            
            # 2. Check IPv4 format: ip:port
            ipv4_port_match = re.match(r'^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+):(\d+)$', address)
            if ipv4_port_match:
                ip, port = ipv4_port_match.group(1), int(ipv4_port_match.group(2))
                try:
                    ipaddress.IPv4Address(ip)
                    if ip_ver == "v6":
                        return self._make_error(
                            f"Указана версия v6, но адрес IPv4: '{address}'",
                            self.IP_PORT_COLUMN
                        )
                    if not (1 <= port <= 65535):
                        return self._make_error(f"Порт вне диапазона: {port}", self.IP_PORT_COLUMN)
                    return ""
                except:
                    return self._make_error(f"Некорректный IPv4: '{ip}'", self.IP_PORT_COLUMN)
            
            # 3. Check bare IPv4 (without port) - OK if Port column has data
            ipv4_bare_match = re.match(r'^([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)$', address)
            if ipv4_bare_match:
                ip = ipv4_bare_match.group(1)
                try:
                    ipaddress.IPv4Address(ip)
                    if ip_ver == "v6":
                        return self._make_error(
                            f"Указана версия v6, но адрес IPv4: '{address}'",
                            self.IP_PORT_COLUMN
                        )
                    return ""  # OK - port is in separate column
                except:
                    return self._make_error(f"Некорректный IPv4: '{ip}'", self.IP_PORT_COLUMN)
            
            # 4. Check bare IPv6 (without port) - OK if Port column has data
            # IPv6 contains colons and hex digits
            if ':' in address and not address.startswith('['):
                try:
                    ipaddress.IPv6Address(address)
                    if ip_ver == "v4":
                        return self._make_error(
                            f"Указана версия v4, но адрес IPv6: '{address}'",
                            self.IP_PORT_COLUMN
                        )
                    return ""  # OK - port is in separate column
                except:
                    return self._make_error(f"Некорректный IPv6: '{address}'", self.IP_PORT_COLUMN)
            
            return self._make_error(f"Некорректный формат: '{address}'", self.IP_PORT_COLUMN)
        
        errors = df.apply(check_format, axis=1)
        return errors


class BlacklistValidator(DataFrameValidator):
    """Validates that IP is not in blacklisted subnets."""
    
    def __init__(self, blacklist: Dict[str, List[str]]):
        self.NETWORK_COLUMN = COLUMNS[5].name  # "Сеть в формате network ID"
        self.MASK_COLUMN = COLUMNS[6].name  # "Маска"
        self._blacklist = blacklist
        self._parsed_subnets = []
        for source, subnets in blacklist.items():
            for subnet_str in subnets:
                try:
                    net = ipaddress.ip_network(subnet_str, strict=False)
                    self._parsed_subnets.append((source, net))
                except:
                    pass
    
    @property
    def name(self) -> str:
        return "BLACKLIST"
    
    @property
    def description(self) -> str:
        return "Проверка blacklist"
    
    def validate(self, df: pd.DataFrame) -> pd.Series:
        errors = self._empty_errors(df)
        
        if self.NETWORK_COLUMN not in df.columns or not self._parsed_subnets:
            return errors
        
        def check_blacklist(row) -> str:
            network_str = str(row[self.NETWORK_COLUMN]).strip()
            mask_str = str(row[self.MASK_COLUMN]).strip()
            if not network_str or network_str == "nan":
                return ""
            
            try:
                ip = ipaddress.ip_address(network_str)
            except:
                return ""  # Format error handled elsewhere
            
            for source, subnet in self._parsed_subnets:
                if ip in subnet:
                    # Если совпадение найдено, проверяем исключение:
                    # Если blacklist подсеть - это хост (/32 для IPv4 или /128 для IPv6)
                    # То это допустимо (независимо от маски проверяемого адреса)
                    is_blacklist_host = (
                        (mask_str == "/32" and isinstance(subnet, ipaddress.IPv4Network)) or
                        (mask_str == "/128" and isinstance(subnet, ipaddress.IPv6Network))
                    )
                    if is_blacklist_host:

                        continue
                    
                    return self._make_error(
                        f"IP в blacklist подсети {subnet} (источник: {source})",
                        self.NETWORK_COLUMN
                    )
            return ""
        
        errors = df.apply(check_blacklist, axis=1)
        
        return errors

