from abc import ABC, abstractmethod
from typing import Dict, Tuple, Any, Optional
from pathlib import Path
import json
import logging
from .interfaces import SerumParameters, ParameterConstraintSet

class ISerumParameterManager(ABC):
    """Interface for Serum parameter management."""

    @abstractmethod
    def load_parameters(self, fx_params_path: Path) -> Dict[str, Dict[str, Any]]:
        """Load parameter definitions from fx_parameters.json."""
        pass

    @abstractmethod
    def validate_parameter_value(self, param_id: str, value: float) -> bool:
        """Validate a parameter value against its defined range."""
        pass

    @abstractmethod
    def get_parameter_bounds(self, param_id: str) -> Tuple[float, float]:
        """Get min/max bounds for a parameter."""
        pass

    @abstractmethod
    def validate_constraint_set(self, constraint_set: ParameterConstraintSet) -> bool:
        """Validate that all constraints are within parameter bounds."""
        pass

    @abstractmethod
    def get_default_parameters(self) -> SerumParameters:
        """Get default parameter values for all Serum parameters."""
        pass


class SerumParameterManager(ISerumParameterManager):
    """Implementation of Serum parameter management."""
    
    def __init__(self, fx_params_path: Path):
        """
        Initialize the SerumParameterManager.
        
        Args:
            fx_params_path: Path to the fx_parameters.json file
            
        Raises:
            FileNotFoundError: If the parameters file doesn't exist
            ValueError: If the JSON file is malformed or missing required data
        """
        self.fx_params_path = fx_params_path
        self.logger = logging.getLogger(__name__)
        
        # Load and parse parameters
        self.raw_data = self._load_json_file()
        self.parameters = self._parse_parameters()
        self.param_lookup = self._build_parameter_lookup()
        
        self.logger.info(f"Loaded {len(self.parameters)} Serum parameters from {fx_params_path}")
    
    def load_parameters(self, fx_params_path: Path) -> Dict[str, Dict[str, Any]]:
        """
        Load parameter definitions from fx_parameters.json.
        
        Args:
            fx_params_path: Path to the parameters file
            
        Returns:
            Dictionary mapping parameter IDs to parameter definitions
        """
        self.fx_params_path = fx_params_path
        self.raw_data = self._load_json_file()
        self.parameters = self._parse_parameters()
        self.param_lookup = self._build_parameter_lookup()
        return self.parameters
    
    def validate_parameter_value(self, param_id: str, value: float) -> bool:
        """
        Validate a parameter value against its defined range.
        
        Args:
            param_id: The parameter identifier
            value: The value to validate
            
        Returns:
            True if the value is within bounds, False otherwise
        """
        if param_id not in self.parameters:
            self.logger.warning(f"Parameter '{param_id}' not found")
            return False
            
        param = self.parameters[param_id]
        min_val = param['min_value']
        max_val = param['max_value']
        
        is_valid = min_val <= value <= max_val
        
        if not is_valid:
            self.logger.debug(
                f"Parameter '{param_id}' value {value} outside bounds [{min_val}, {max_val}]"
            )
            
        return is_valid
    
    def get_parameter_bounds(self, param_id: str) -> Tuple[float, float]:
        """
        Get min/max bounds for a parameter.
        
        Args:
            param_id: The parameter identifier
            
        Returns:
            Tuple of (min_value, max_value)
            
        Raises:
            KeyError: If parameter doesn't exist
        """
        if param_id not in self.parameters:
            raise KeyError(f"Parameter '{param_id}' not found")
            
        param = self.parameters[param_id]
        return (param['min_value'], param['max_value'])
    
    def validate_constraint_set(self, constraint_set: ParameterConstraintSet) -> bool:
        """
        Validate that all constraints are within parameter bounds.
        
        Args:
            constraint_set: Dictionary mapping parameter IDs to (min, max) constraint tuples
            
        Returns:
            True if all constraints are valid, False otherwise
        """
        for param_id, (constraint_min, constraint_max) in constraint_set.items():
            # Check if parameter exists
            if param_id not in self.parameters:
                self.logger.error(f"Constraint references unknown parameter '{param_id}'")
                return False
            
            # Check constraint validity
            if constraint_min > constraint_max:
                self.logger.error(
                    f"Invalid constraint for '{param_id}': min {constraint_min} > max {constraint_max}"
                )
                return False
            
            # Check if constraints are within parameter bounds
            param_min, param_max = self.get_parameter_bounds(param_id)
            
            if constraint_min < param_min or constraint_max > param_max:
                self.logger.error(
                    f"Constraint for '{param_id}' [{constraint_min}, {constraint_max}] "
                    f"outside parameter bounds [{param_min}, {param_max}]"
                )
                return False
        
        return True
    
    def get_default_parameters(self) -> SerumParameters:
        """
        Get default parameter values for all Serum parameters.
        
        Returns:
            Dictionary mapping parameter IDs to their default values
        """
        defaults = {}
        for param_id, param in self.parameters.items():
            # Use mid_value as default if available, otherwise use normalized_value or calculate middle
            if 'mid_value' in param and param['mid_value'] is not None:
                defaults[param_id] = param['mid_value']
            elif 'normalized_value' in param and param['normalized_value'] is not None:
                defaults[param_id] = param['normalized_value']
            else:
                # Calculate middle value as fallback
                min_val = param['min_value']
                max_val = param['max_value']
                defaults[param_id] = (min_val + max_val) / 2.0
        
        return defaults
    
    def get_parameter_info(self, param_id: str) -> Optional[Dict[str, Any]]:
        """
        Get complete parameter information.
        
        Args:
            param_id: The parameter identifier
            
        Returns:
            Dictionary with parameter information or None if not found
        """
        return self.parameters.get(param_id)
    
    def get_parameter_name(self, param_id: str) -> Optional[str]:
        """
        Get the human-readable name of a parameter.
        
        Args:
            param_id: The parameter identifier
            
        Returns:
            Parameter name or None if not found
        """
        param = self.parameters.get(param_id)
        return param.get('name') if param else None
    
    def get_all_parameter_ids(self) -> list[str]:
        """
        Get list of all parameter IDs.
        
        Returns:
            List of all parameter identifiers
        """
        return list(self.parameters.keys())
    
    def _load_json_file(self) -> Dict[str, Any]:
        """
        Load and parse the JSON parameters file.
        
        Returns:
            Parsed JSON data
            
        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If JSON is malformed
        """
        if not self.fx_params_path.exists():
            raise FileNotFoundError(f"Parameters file not found: {self.fx_params_path}")
        
        try:
            with open(self.fx_params_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in parameters file: {e}")
        except Exception as e:
            raise ValueError(f"Error reading parameters file: {e}")
    
    def _parse_parameters(self) -> Dict[str, Dict[str, Any]]:
        """
        Parse parameters from the loaded JSON data.
        
        Returns:
            Dictionary mapping parameter IDs to parameter definitions
            
        Raises:
            ValueError: If required data structure is missing
        """
        try:
            # Navigate the JSON structure: fx_data -> first plugin -> parameters
            fx_data = self.raw_data.get('fx_data', {})
            if not fx_data:
                raise ValueError("No 'fx_data' section found in parameters file")
            
            # Get the first (and likely only) plugin entry
            plugin_data = next(iter(fx_data.values()), {})
            if not plugin_data:
                raise ValueError("No plugin data found in fx_data section")
            
            # Extract parameters
            raw_params = plugin_data.get('parameters', {})
            if not raw_params:
                raise ValueError("No parameters found in plugin data")
            
            # Convert to our format, using string keys as parameter IDs
            parameters = {}
            for param_id, param_data in raw_params.items():
                parameters[param_id] = {
                    'name': param_data.get('name', f'Parameter_{param_id}'),
                    'min_value': float(param_data.get('min_value', 0.0)),
                    'max_value': float(param_data.get('max_value', 1.0)),
                    'mid_value': param_data.get('mid_value'),
                    'normalized_value': param_data.get('normalized_value'),
                    'identifier': param_data.get('identifier'),
                    'formatted_value': param_data.get('formatted_value')
                }
                
                # Ensure mid_value is float if present
                if parameters[param_id]['mid_value'] is not None:
                    parameters[param_id]['mid_value'] = float(parameters[param_id]['mid_value'])
                
                # Ensure normalized_value is float if present
                if parameters[param_id]['normalized_value'] is not None:
                    parameters[param_id]['normalized_value'] = float(parameters[param_id]['normalized_value'])
            
            return parameters
            
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Error parsing parameters: {e}")
    
    def _build_parameter_lookup(self) -> Dict[str, str]:
        """
        Build lookup tables for efficient parameter access.
        
        Returns:
            Dictionary mapping parameter names to parameter IDs
        """
        lookup = {}
        for param_id, param in self.parameters.items():
            name = param.get('name')
            if name:
                lookup[name.lower()] = param_id
        return lookup
    
    def find_parameter_by_name(self, name: str) -> Optional[str]:
        """
        Find parameter ID by name (case-insensitive).
        
        Args:
            name: Parameter name to search for
            
        Returns:
            Parameter ID or None if not found
        """
        return self.param_lookup.get(name.lower())