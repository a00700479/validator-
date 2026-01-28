"""Service for searching IP addresses in CSV files."""
import ipaddress
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import pandas as pd
from dataclasses import dataclass

from config.settings import Settings
from config.columns import COLUMN_NAMES, COLUMNS


@dataclass
class SearchMatch:
    """Represents a match found in CSV file."""
    file_path: str
    line_number: int
    ip_searched: str
    network_found: str
    mask_found: str
    subnet: str
    row_data: Dict[str, str]
    match_type: str  # 'exact' or 'subnet'


@dataclass
class SearchResult:
    """Result of searching addresses across files."""
    searched_addresses: List[str]
    matches: List[SearchMatch]
    files_checked: int
    files_with_warnings: List[Tuple[str, str]]  # (filepath, warning_message)


class SearchService:
    """Service for searching IP addresses in CSV files with subnet matching."""
    
    def __init__(self, settings: Settings):
        self._settings = settings
        self.NETWORK_COLUMN = COLUMNS[5].name  # "Сеть в формате network ID"
    
    def search_addresses_in_files(
        self,
        addresses: List[str],
        file_paths: List[str]
    ) -> SearchResult:
        """
        Search for IP addresses in CSV files with subnet matching.
        
        Args:
            addresses: List of IP addresses to search
            file_paths: List of CSV file paths to search in
            
        Returns:
            SearchResult with all matches found
        """
        matches = []
        files_with_warnings = []
        files_checked = 0
        
        for file_path in file_paths:
            if not Path(file_path).exists():
                files_with_warnings.append((file_path, "Файл не найден"))
                continue
            
            files_checked += 1
            
            # Try to read and validate file format
            df, format_warning = self._read_and_validate_csv(file_path)
            
            if format_warning:
                files_with_warnings.append((file_path, format_warning))
            
            if df is None or df.empty:
                continue
            
            # Search for addresses in this file
            file_matches = self._search_in_dataframe(addresses, df, file_path)
            matches.extend(file_matches)
        
        return SearchResult(
            searched_addresses=addresses,
            matches=matches,
            files_checked=files_checked,
            files_with_warnings=files_with_warnings
        )
    
    def _read_and_validate_csv(self, file_path: str) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        """
        Read CSV file and validate format.
        
        Returns:
            Tuple of (DataFrame or None, warning message or None)
        """
        try:
            # Try reading with expected format
            df = pd.read_csv(
                file_path,
                sep=self._settings.csv_delimiter,
                encoding=self._settings.csv_encoding,
                dtype=str,
                keep_default_na=False,
            )
            
            if df.empty:
                return None, "Файл пуст"
            
            # Check if headers match expected format
            expected_columns = set(COLUMN_NAMES)
            actual_columns = set(df.columns)
            
            if expected_columns != actual_columns:
                # Try to find required columns anyway
                required_cols = {self.NETWORK_COLUMN, "MASK", "IPv4/IPv6"}
                missing_required = required_cols - actual_columns
                
                if missing_required:
                    return None, f"⚠️  Формат не соответствует ожидаемому, отсутствуют колонки: {missing_required}"
                else:
                    # Has required columns but format differs
                    return df, "⚠️  Формат файла отличается от стандартного, но необходимые колонки найдены"
            
            return df, None
            
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                df = pd.read_csv(
                    file_path,
                    sep=self._settings.csv_delimiter,
                    encoding='cp1251',
                    dtype=str,
                    keep_default_na=False,
                )
                return df, "⚠️  Файл использует кодировку CP1251 вместо UTF-8"
            except:
                return None, "Ошибка чтения: неподдерживаемая кодировка"
        
        except pd.errors.ParserError:
            # Try different delimiter
            try:
                df = pd.read_csv(
                    file_path,
                    sep=',',
                    encoding=self._settings.csv_encoding,
                    dtype=str,
                    keep_default_na=False,
                )
                return df, "⚠️  Файл использует ',' вместо '|' в качестве разделителя"
            except:
                return None, "Ошибка парсинга CSV"
        
        except Exception as e:
            return None, f"Ошибка чтения файла: {str(e)}"
    
    def _search_in_dataframe(
        self,
        addresses: List[str],
        df: pd.DataFrame,
        file_path: str
    ) -> List[SearchMatch]:
        """
        Search for addresses in DataFrame with subnet matching.
        
        Args:
            addresses: List of IP addresses to search
            df: DataFrame to search in
            file_path: Path to source file (for reporting)
            
        Returns:
            List of SearchMatch objects
        """
        matches = []
        
        # Check if required columns exist
        if self.NETWORK_COLUMN not in df.columns or "MASK" not in df.columns:
            return matches
        
        # Get IP version column if exists
        ip_version_col = df["IPv4/IPv6"] if "IPv4/IPv6" in df.columns else None
        
        # Iterate through each row
        for idx, row in df.iterrows():
            network_str = str(row.get(self.NETWORK_COLUMN, "")).strip()
            mask_str = str(row.get("MASK", "")).strip()
            
            if not network_str or network_str == "nan":
                continue
            
            # Extract mask value
            if mask_str.startswith("/"):
                mask_str = mask_str[1:]
            
            try:
                mask_bits = int(mask_str)
            except (ValueError, AttributeError):
                continue
            
            # Build subnet
            try:
                subnet_str = f"{network_str}/{mask_bits}"
                subnet = ipaddress.ip_network(subnet_str, strict=False)
            except ValueError:
                continue
            
            # Check each search address
            for search_addr in addresses:
                try:
                    search_ip = ipaddress.ip_address(search_addr)
                    
                    # Check if IP is in subnet
                    if search_ip in subnet:
                        # Determine match type
                        match_type = "exact" if str(search_ip) == network_str else "subnet"
                        
                        # Build row data dict
                        row_data = {}
                        for col in df.columns:
                            val = row.get(col, "")
                            if pd.notna(val) and str(val) != "nan":
                                row_data[col] = str(val)
                        
                        match = SearchMatch(
                            file_path=file_path,
                            line_number=idx + 2,  # +2 for header and 0-based index
                            ip_searched=search_addr,
                            network_found=network_str,
                            mask_found=f"/{mask_bits}",
                            subnet=subnet_str,
                            row_data=row_data,
                            match_type=match_type
                        )
                        matches.append(match)
                
                except ValueError:
                    # Invalid IP address
                    continue
        
        return matches

