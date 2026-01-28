"""Validation pipeline with progress tracking."""
from typing import List, Optional, Callable
import pandas as pd
from tqdm import tqdm

from validators.base import DataFrameValidator
from validators.df_validators import (
    RequiredFieldsValidator,
    UniqueNumberValidator,
    OgrnValidator,
    IpVersionValidator,
    MaskFormatValidator,
    PortFormatValidator,
    CdnValidator,
    ProtocolValidator,
    MethodValidator,
    NetworkFormatValidator,
    HostBitsValidator,
    CheckIpPortFormatValidator,
    BlacklistValidator,
)
from validators.whois_validator import WhoisCountryValidator
from config.settings import Settings
from domain.entities import ValidationReport


class ValidationPipeline:
    """
    Orchestrates DataFrame validation with progress tracking.
    
    Applies validators sequentially and collects errors into
    a result column.
    """
    
    def __init__(self, settings: Settings):
        self._settings = settings
        self._whois_validator = WhoisCountryValidator()
        self._validators: List[DataFrameValidator] = []
        self._build_validators()
    
    def _build_validators(self) -> None:
        """Build list of validators based on settings."""
        self._validators = [
            RequiredFieldsValidator(),
            UniqueNumberValidator(),
            OgrnValidator(),
            IpVersionValidator(),
            NetworkFormatValidator(),
            MaskFormatValidator(),
            HostBitsValidator(),
            PortFormatValidator(),
            CdnValidator(),
            ProtocolValidator(),
            CheckIpPortFormatValidator(),
            MethodValidator(),
        ]
        
        # Add blacklist validator if configured
        if self._settings.blacklist:
            self._validators.append(BlacklistValidator(self._settings.blacklist))
        
        # Add whois validator if enabled and available
        if self._settings.whois_enabled and self._whois_validator.is_available():
            self._validators.append(self._whois_validator)
    
    def get_whois_startup_warning(self) -> Optional[str]:
        """Get whois startup warning if applicable."""
        return self._whois_validator.get_startup_warning()
    
    def get_whois_final_warning(self) -> Optional[str]:
        """Get whois final warning if applicable."""
        return self._whois_validator.get_final_warning()
    
    def validate(
        self,
        df: pd.DataFrame,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> ValidationReport:
        """
        Validate DataFrame through all validators with progress tracking.
        
        Args:
            df: DataFrame to validate
            progress_callback: Optional callback(validator_name, current, total)
            
        Returns:
            ValidationReport with results
        """
        total_validators = len(self._validators)
        
        # Initialize errors column
        all_errors = pd.Series("", index=df.index)
        
        # Run each validator with progress bar
        with tqdm(
            self._validators,
            desc="Валидация",
            unit="проверка",
            ncols=80,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]"
        ) as pbar:
            for i, validator in enumerate(pbar):
                # Update progress bar description
                pbar.set_postfix_str(validator.description[:30])
                
                # Run validator
                errors = validator.validate(df)
                
                # Combine errors
                all_errors = all_errors.str.cat(errors, sep="; ", na_rep="")
                all_errors = all_errors.str.strip("; ").str.replace(r"^; |; $", "", regex=True)
                all_errors = all_errors.str.replace(r"; +; ", "; ", regex=True)
                
                # Call progress callback if provided
                if progress_callback:
                    progress_callback(validator.name, i + 1, total_validators)
        
        # Clean up errors
        all_errors = all_errors.str.strip("; ")
        
        # Create result column
        result_column = all_errors.apply(lambda x: "ok" if not x else x)
        
        # Calculate statistics
        total_rows = len(df)
        valid_rows = (result_column == "ok").sum()
        
        # Create error details DataFrame
        error_mask = result_column != "ok"
        
        # Get Number column values for error rows, fallback to line number if missing
        if "Number" in df.columns:
            numbers = df.loc[error_mask, "Number"].tolist()
        else:
            numbers = (df.index[error_mask] + 2).tolist()  # Fallback to line numbers
        
        error_details = pd.DataFrame({
            "number": numbers,
            "errors": all_errors[error_mask].tolist()
        })
        
        return ValidationReport(
            total_rows=total_rows,
            valid_rows=valid_rows,
            error_details=error_details,
            result_column=result_column
        )
    
    def validate_with_live_progress(self, df: pd.DataFrame) -> ValidationReport:
        """
        Validate with live progress display to console.
        
        Args:
            df: DataFrame to validate
            
        Returns:
            ValidationReport with results
        """
        print(f"\n📊 Валидация {len(df)} строк...\n")
        
        return self.validate(df)
