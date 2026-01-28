from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Settings:
    csv_delimiter: str = "|"
    csv_encoding: str = "utf-8-sig"
    threads: int = 4
    whois_timeout: int = 10
    whois_enabled: bool = True
    result_column_name: str = "результат проверки"
    input_file: Optional[str] = None
    output_file: Optional[str] = None
    blacklist_file: Optional[str] = None
    blacklist: dict[str, list[str]] = field(default_factory=dict)

