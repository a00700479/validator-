import ipaddress
import re
import socket
from typing import Optional, Tuple


def is_ipv4(ip: str) -> bool:
    """Check if string is a valid IPv4 address."""
    try:
        socket.inet_pton(socket.AF_INET, ip)
        return True
    except socket.error:
        return False


def is_ipv6(ip: str) -> bool:
    """Check if string is a valid IPv6 address."""
    try:
        socket.inet_pton(socket.AF_INET6, ip)
        return True
    except socket.error:
        return False


def parse_ip_port(address: str) -> Tuple[Optional[str], Optional[int]]:
    """
    Parse address string into IP and port.
    
    Supports formats:
    - IPv4:port (e.g., 192.168.1.1:443)
    - [IPv6]:port (e.g., [2001:db8::1]:443)
    - IPv4 or IPv6 without port
    
    Returns:
        Tuple of (ip, port) or (None, None) on error
    """
    if not address:
        return None, None
    
    address = address.strip()
    
    ipv6_with_port = re.match(r'^\[([0-9a-fA-F:]+)\]:(\d+)$', address)
    if ipv6_with_port:
        ip = ipv6_with_port.group(1)
        port = int(ipv6_with_port.group(2))
        return ip, port
    
    ipv4_with_port = re.match(r'^([0-9.]+):(\d+)$', address)
    if ipv4_with_port:
        ip = ipv4_with_port.group(1)
        port = int(ipv4_with_port.group(2))
        return ip, port
    
    if is_ipv4(address) or is_ipv6(address):
        return address, None
    
    return None, None


def get_mask_bits(mask: str) -> Optional[int]:
    if not mask:
        return None
    
    mask = mask.strip()
    if mask.startswith("/"):
        mask = mask[1:]
    
    try:
        bits = int(mask)
        if 0 <= bits <= 128:
            return bits
        return None
    except ValueError:
        return None


def validate_network_mask(network: str, mask: str, ip_version: str) -> Tuple[bool, Optional[str]]:
    if not network or not mask:
        return False, "Сеть или маска не указаны"
    
    mask_bits = get_mask_bits(mask)
    if mask_bits is None:
        return False, f"Некорректный формат маски: {mask}"
    
    try:
        network_str = f"{network}/{mask_bits}"
        
        if ip_version == "v4":
            net = ipaddress.IPv4Network(network_str, strict=True)
        elif ip_version == "v6":
            net = ipaddress.IPv6Network(network_str, strict=True)
        else:
            return False, f"Некорректная версия IP: {ip_version}"
        return True, None
        
    except ValueError as e:
        error_str = str(e)
        if "has host bits set" in error_str.lower():
            try:
                if ip_version == "v4":
                    net = ipaddress.IPv4Network(network_str, strict=False)
                else:
                    net = ipaddress.IPv6Network(network_str, strict=False)
                return False, f"{network} {mask} -> Host bits set; canonical network: {net.network_address}/{mask_bits}"
            except Exception:
                pass
        return False, f"Ошибка валидации сети: {error_str}"


def ip_in_subnet(ip: str, subnet: str) -> bool:
    """
    Check if IP address is in the given subnet.
    
    Args:
        ip: IP address string
        subnet: Subnet in CIDR notation (e.g., "192.168.0.0/16")
        
    Returns:
        True if IP is in subnet, False otherwise
    """
    try:
        ip_obj = ipaddress.ip_address(ip)
        network_obj = ipaddress.ip_network(subnet, strict=False)
        return ip_obj in network_obj
    except ValueError:
        return False


def get_subnet_mask_bits(subnet: str) -> Optional[int]:
    """
    Get the mask bits from a subnet string.
    
    Args:
        subnet: Subnet in CIDR notation (e.g., "192.168.0.0/16")
        
    Returns:
        Mask bits or None if invalid
    """
    try:
        network = ipaddress.ip_network(subnet, strict=False)
        return network.prefixlen
    except ValueError:
        return None

