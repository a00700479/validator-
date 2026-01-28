"""Abstract base classes for validators."""
from abc import ABC, abstractmethod
from typing import Optional

from .entities import Row, ValidationError


class BaseValidator(ABC):
    """Abstract base class for all validators."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Validator name for logging."""
        pass
    
    @abstractmethod
    def validate(self, row: Row) -> Optional[ValidationError]:
        """
        Validate a single row.
        
        Args:
            row: Row to validate
            
        Returns:
            ValidationError if validation failed, None otherwise
        """
        pass


class FileValidator(ABC):
    """Abstract base class for file-level validators."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Validator name for logging."""
        pass
    
    @abstractmethod
    def validate(self, filepath: str) -> list[ValidationError]:
        """
        Validate file-level properties.
        
        Args:
            filepath: Path to the CSV file
            
        Returns:
            List of validation errors (empty if valid)
        """
        pass

