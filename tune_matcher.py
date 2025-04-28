import os
import json
import zipfile
import tempfile
import re
import shutil
import logging
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger('RFTX.TuneMatcher')

class TuneMatcher:
    def __init__(self, tunes_directory: str = "."):
        """Initialize the TuneMatcher with the directory containing tune zip files."""
        self.tunes_directory = tunes_directory
        self.temp_dir = tempfile.mkdtemp()
        self.available_tunes = []
        self.extracted_paths = {}
        
    def scan_available_tunes(self) -> List[str]:
        """Scan the tunes directory for available zip files."""
        self.available_tunes = [f for f in os.listdir(self.tunes_directory) 
                               if f.endswith('.zip') and os.path.isfile(os.path.join(self.tunes_directory, f))]
        logger.info(f"Found {len(self.available_tunes)} tune packages: {', '.join(self.available_tunes)}")
        return self.available_tunes
    
    def extract_tune_zip(self, zip_filename: str) -> str:
        """Extract a tune zip file to a temporary directory."""
        if zip_filename in self.extracted_paths:
            return self.extracted_paths[zip_filename]
            
        zip_path = os.path.join(self.tunes_directory, zip_filename)
        extract_path = os.path.join(self.temp_dir, os.path.splitext(zip_filename)[0])
        
        os.makedirs(extract_path, exist_ok=True)
        
        logger.info(f"Extracting {zip_filename} to temporary directory")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_path)
            
        self.extracted_paths[zip_filename] = extract_path
        return extract_path
    
    def find_tune_info_json(self, extract_path: str) -> Optional[Dict]:
        """Look for tune_info.json in the extracted directory."""
        json_path = os.path.join(extract_path, 'tune_info.json')
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    tune_info = json.load(f)
                    logger.info(f"Found tune_info.json with {len(tune_info.get('tunes', []))} tune definitions")
                    return tune_info
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in tune_info.json")
                return None
        return None
    
    def find_matching_tunes(self, vin: str, ecu_id: str, sw_version: str) -> List[Dict]:
        """Find tunes that match the car's ECU information."""
        matching_tunes = []
        
        # Extract ECU type and engine code
        ecu_type = self._extract_ecu_type(ecu_id)
        engine_code = self._extract_engine_code(ecu_id, sw_version)
        
        logger.info(f"Searching for tunes matching ECU type: {ecu_type}, Engine: {engine_code}")
        
        # Scan all available tune zip files
        for zip_file in self.scan_available_tunes():
            extract_path = self.extract_tune_zip(zip_file)
            
            # Check if there's a tune_info.json for better matching
            tune_info = self.find_tune_info_json(extract_path)
            
            # Walk through the extracted directory to find .bin files
            for root, dirs, files in os.walk(extract_path):
                for file in files:
                    if file.endswith('.bin'):
                        # Determine tune type from folder structure and filename
                        relative_path = os.path.relpath(root, extract_path)
                        tune_type = self._determine_tune_type(relative_path, file)
                        
                        # Check if this tune matches the ECU
                        match_confidence = self._check_tune_match(
                            file, relative_path, tune_info, 
                            vin, ecu_id, sw_version, ecu_type, engine_code
                        )
                        
                        if match_confidence > 0:
                            matching_tunes.append({
                                'zip_file': zip_file,
                                'bin_file': file,
                                'relative_path': relative_path,
                                'full_path': os.path.join(root, file),
                                'tune_type': tune_type,
                                'match_confidence': match_confidence,
                                'ecu_type': ecu_type,
                                'engine_code': engine_code
                            })
        
        # Sort by match confidence (higher is better)
        matching_tunes.sort(key=lambda x: x['match_confidence'], reverse=True)
        logger.info(f"Found {len(matching_tunes)} matching tunes")
        return matching_tunes
    
    def _extract_ecu_type(self, ecu_id: str) -> str:
        """Extract the ECU type from the ECU ID."""
        # Common BMW ECU types
        ecu_patterns = [
            r'MSD8[0-9]',    # MSD80, MSD81, etc.
            r'MEVD17\.[0-9]', # MEVD17.x
            r'MG1',          # MG1
            r'MD1',          # MD1
            r'MSV[0-9]+',    # MSV70, MSV80, etc.
            r'DME[0-9]*'     # DME, DME7, etc.
        ]
        
        for pattern in ecu_patterns:
            match = re.search(pattern, ecu_id, re.IGNORECASE)
            if match:
                return match.group(0).upper()
        
        return "UNKNOWN"
    
    def _extract_engine_code(self, ecu_id: str, sw_version: str) -> str:
        """Extract the engine code from ECU ID or software version."""
        # Common BMW engine codes
        engine_patterns = [
            r'N54',
            r'N55',
            r'S55',
            r'B58',
            r'S58',
            r'N52',
            r'N20',
            r'B48'
        ]
        
        # Check in both ECU ID and software version
        combined = ecu_id + " " + sw_version
        
        for pattern in engine_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return pattern.upper()
        
        return "UNKNOWN"
    
    def _determine_tune_type(self, relative_path: str, filename: str) -> str:
        """Determine the tune type from the path and filename."""
        # Check for common tune type indicators in the path
        path_lower = relative_path.lower()
        file_lower = filename.lower()
        combined = path_lower + " " + file_lower
        
        # Look for stage information
        stage_match = re.search(r'stage\s*(\d+)', combined)
        stage = f"Stage {stage_match.group(1)}" if stage_match else ""
        
        # Look for fuel type
        fuel_type = ""
        if "e85" in combined:
            fuel_type = "E85"
        elif "e50" in combined:
            fuel_type = "E50"
        elif "e30" in combined:
            fuel_type = "E30"
        elif "pump" in combined or "91" in combined or "93" in combined:
            octane_match = re.search(r'(\d{2,3})oct', combined)
            if octane_match:
                fuel_type = f"{octane_match.group(1)} Octane"
            else:
                fuel_type = "Pump Gas"
            
        # Look for turbo configuration
        turbo_config = ""
        if "single turbo" in combined or "single_turbo" in combined:
            turbo_config = "Single Turbo"
        elif "hybrid turbo" in combined or "hybrid_turbo" in combined:
            turbo_config = "Hybrid Turbo"
        elif "stock turbo" in combined or "stock_turbo" in combined:
            turbo_config = "Stock Turbo"
            
        # Look for special features
        features = []
        if "burble" in combined:
            features.append("Burble")
        if "pops" in combined:
            features.append("Pops & Bangs")
        if "meth" in combined or "methanol" in combined:
            features.append("Methanol")
        if "race" in combined:
            features.append("Race")
        if "track" in combined:
            features.append("Track")
        if "stock" in combined and "turbo" not in combined:
            features.append("Stock")
        
        # Combine the information
        tune_parts = [p for p in [stage, fuel_type, turbo_config] if p]
        if features:
            tune_parts.append("(" + ", ".join(features) + ")")
            
        if tune_parts:
            return " ".join(tune_parts)
        
        # If we couldn't determine a specific type, use the filename without extension
        return os.path.splitext(filename)[0]
    
    def _check_tune_match(self, filename: str, relative_path: str, 
                         tune_info: Optional[Dict], vin: str, 
                         ecu_id: str, sw_version: str,
                         ecu_type: str, engine_code: str) -> int:
        """
        Check if a tune matches the car's ECU.
        Returns a confidence score (0-100) where higher is better match.
        """
        confidence = 0
        path_and_file = (relative_path + '/' + filename).lower()
        
        # If we have tune_info.json, use it for precise matching
        if tune_info:
            for tune in tune_info.get('tunes', []):
                # Check for direct ECU ID match
                if tune.get('ecu_id') == ecu_id:
                    # Check if this specific bin file is mentioned
                    if filename in tune.get('bin_files', []) or relative_path in tune.get('paths', []):
                        return 100  # Perfect match from tune_info.json
                    confidence = max(confidence, 90)
                
                # Check for software version match
                elif tune.get('sw_version') == sw_version:
                    if filename in tune.get('bin_files', []) or relative_path in tune.get('paths', []):
                        return 95  # Very good match from tune_info.json
                    confidence = max(confidence, 85)
                
                # Check for VIN pattern match
                elif tune.get('vin_pattern') and re.search(tune.get('vin_pattern'), vin):
                    if filename in tune.get('bin_files', []) or relative_path in tune.get('paths', []):
                        return 90  # Good match from tune_info.json
                    confidence = max(confidence, 80)
                
                # Check for ECU type match
                elif tune.get('ecu_type') == ecu_type:
                    if filename in tune.get('bin_files', []) or relative_path in tune.get('paths', []):
                        return 85  # Good match from tune_info.json
                    confidence = max(confidence, 75)
                
                # Check for engine code match
                elif tune.get('engine_code') == engine_code:
                    if filename in tune.get('bin_files', []) or relative_path in tune.get('paths', []):
                        return 80  # Good match from tune_info.json
                    confidence = max(confidence, 70)
        
        # Direct matching based on path and filename
        if ecu_id.lower() in path_and_file:
            confidence = max(confidence, 90)
        elif ecu_type.lower() in path_and_file:
            confidence = max(confidence, 80)
        elif sw_version.lower() in path_and_file:
            confidence = max(confidence, 85)
        elif engine_code.lower() in path_and_file:
            confidence = max(confidence, 75)
            
        # Check for common BMW engine codes in the path if we don't already have a match
        if confidence < 60 and engine_code != "UNKNOWN":
            if engine_code.lower() in path_and_file:
                confidence = max(confidence, 60)
                
        # If we have no better match but the file is in a folder structure that seems relevant
        if confidence == 0:
            relevant_terms = ['ecu', 'tune', 'flash', 'bin', 'map', 'bmw', 'dme', 'calibration']
            for term in relevant_terms:
                if term in path_and_file:
                    confidence = max(confidence, 30)
                    break
            
        return confidence
    
    def cleanup(self):
        """Clean up temporary files."""
        try:
            shutil.rmtree(self.temp_dir)
            logger.info("Cleaned up temporary files")
        except Exception as e:
            logger.error(f"Error cleaning up temporary files: {str(e)}")
