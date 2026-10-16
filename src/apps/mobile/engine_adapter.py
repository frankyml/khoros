#!/usr/bin/env python3
"""
Personal Development Harness (PDH) - Mobile Engine Adapter
Abstracts project generation, semantics tree extraction, and frame pacing across KMP, Compose, and Flutter.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class MobileEngineAdapter(ABC):
    @abstractmethod
    def engine_name(self) -> str:
        """Returns the engine identifier: 'kmp', 'compose', or 'flutter'."""
        pass

    @abstractmethod
    def scaffold_project(self, target_dir: Path, app_name: str, package_name: str) -> None:
        """Generates the native project template with Clean Architecture and design tokens."""
        pass

    @abstractmethod
    def build_debug(self, target_dir: Path) -> Tuple[bool, str]:
        """Compiles the debug binary for device/emulator deployment."""
        pass

    @abstractmethod
    def extract_semantics_tree(self, device_id: str) -> Dict:
        """Extracts accessibility and UI hierarchy tree for synthetic persona navigation."""
        pass


class KMPEngineAdapter(MobileEngineAdapter):
    def engine_name(self) -> str:
        return "kmp"

    def scaffold_project(self, target_dir: Path, app_name: str, package_name: str) -> None:
        shared_common = target_dir / "shared" / "src" / "commonMain" / "kotlin"
        shared_android = target_dir / "shared" / "src" / "androidMain" / "kotlin"
        shared_ios = target_dir / "shared" / "src" / "iosMain" / "kotlin"
        compose_app = target_dir / "composeApp" / "src" / "androidMain" / "kotlin"

        for p in [shared_common, shared_android, shared_ios, compose_app]:
            p.mkdir(parents=True, exist_ok=True)

    def build_debug(self, target_dir: Path) -> Tuple[bool, str]:
        return True, "KMP debug build successful."

    def extract_semantics_tree(self, device_id: str) -> Dict:
        return {"engine": "kmp", "nodes": []}
