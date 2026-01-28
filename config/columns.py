from dataclasses import dataclass
from typing import Optional


@dataclass
class ColumnDefinition:    
    index: int
    name: str
    required: bool
    description: Optional[str] = None


COLUMNS = [
    ColumnDefinition(0, "Number", True, "Порядковый номер записи"),
    ColumnDefinition(1, "Название сервиса", True, "Человекочитаемое имя"),
    ColumnDefinition(2, "юр_лицо", True, "Название юридического лица"),
    ColumnDefinition(3, "ОГРН", True, "Регистрационный номер (13 цифр)"),
    ColumnDefinition(4, "IPv4/IPv6", True, "Версия IP: v4 или v6"),
    ColumnDefinition(5, "Сеть в формате network ID", True, "Network ID"),
    ColumnDefinition(6, "MASK", True, "Префикс в формате /XX"),
    ColumnDefinition(7, "Port", False, "Номер порта"),
    ColumnDefinition(8, "CDN Yes/No", True, "Использование CDN"),
    ColumnDefinition(9, "Protocol", True, "Транспортный протокол"),
    ColumnDefinition(10, "DNS Host", False, "Доменное имя сервиса"),
    ColumnDefinition(11, "SNI/HTTP HOST", False, "Значение для TLS SNI или HTTP Host"),
    ColumnDefinition(12, "Проверочный IP+Порт", True, "Формат ip:port"),
    ColumnDefinition(13, "URL проверки", False, "URL для проверки доступности"),
    ColumnDefinition(14, "Способ проверки", True, "ping, telnet, curl, dig"),
    ColumnDefinition(15, "Описание", False, "Дополнительная информация"),
]

# Column names for header validation
COLUMN_NAMES = [col.name for col in COLUMNS]

# Required columns
REQUIRED_COLUMNS = [col for col in COLUMNS if col.required]

# Valid values for specific columns
VALID_IP_VERSIONS = {"v4", "v6"}
VALID_CDN_VALUES = {"yes", "no"}
VALID_PROTOCOLS = {"tcp", "udp", "esp"}
VALID_CHECK_METHODS = {"ping", "telnet", "curl", "dig"}

