"""
Configuration loading, parsing, and validation.
Edit config.json — never hardcode values here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    project_url: str
    queue_folder: Path
    chrome_profile_path: Path
    chrome_profile_name: str
    skill_name: str
    retry_count: int
    download_timeout: int   # ms
    upload_timeout: int     # ms
    response_timeout: int   # ms
    navigation_timeout: int # ms
    headless: bool
    slow_mo: int            # ms between actions (helps with UI stability)
    log_file: Path

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: Path = Path("config.json")) -> "Config":
        if not path.exists():
            raise FileNotFoundError(
                f"Config file not found: {path}\n"
                "Create config.json from the template and update the values."
            )

        with path.open(encoding="utf-8") as fh:
            raw: dict = json.load(fh)

        required_keys = ("project_url", "queue_folder", "chrome_profile_path")
        missing = [k for k in required_keys if not raw.get(k)]
        if missing:
            raise ValueError(f"Missing required config keys: {missing}")

        return cls(
            project_url=str(raw["project_url"]).strip(),
            queue_folder=Path(raw["queue_folder"]),
            chrome_profile_path=Path(raw["chrome_profile_path"]),
            chrome_profile_name=str(raw.get("chrome_profile_name", "Default")),
            skill_name=str(raw.get("skill_name", "/pr-audit-master")).strip(),
            retry_count=int(raw.get("retry_count", 3)),
            download_timeout=int(raw.get("download_timeout", 120_000)),
            upload_timeout=int(raw.get("upload_timeout", 60_000)),
            response_timeout=int(raw.get("response_timeout", 300_000)),
            navigation_timeout=int(raw.get("navigation_timeout", 30_000)),
            headless=bool(raw.get("headless", False)),
            slow_mo=int(raw.get("slow_mo", 100)),
            log_file=Path(raw.get("log_file", "logs/automation.log")),
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Raise ValueError listing every configuration problem found."""
        errors: list[str] = []

        if "YOUR_PROJECT_ID" in self.project_url or not self.project_url.startswith("http"):
            errors.append(
                "project_url must point to your actual Claude project — "
                "e.g. https://claude.ai/project/abc123def456"
            )

        if not self.chrome_profile_path.exists():
            errors.append(
                f"chrome_profile_path does not exist: {self.chrome_profile_path}\n"
                "  Typical path on Windows: "
                r"C:\Users\<YourName>\AppData\Local\Google\Chrome\User Data"
            )

        if not self.queue_path.exists():
            errors.append(
                f"queue_folder does not exist: {self.queue_path}\n"
                "  Create the Queue directory and add company sub-folders."
            )

        if not self.skill_name.startswith("/"):
            errors.append(
                f"skill_name must start with '/': got '{self.skill_name}'"
            )

        if errors:
            bullet = "\n  • "
            raise ValueError(
                "Configuration errors — fix config.json before running:" +
                bullet + bullet.join(errors)
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def queue_path(self) -> Path:
        """Absolute path to the Queue folder."""
        return (
            self.queue_folder
            if self.queue_folder.is_absolute()
            else Path.cwd() / self.queue_folder
        )

    @property
    def skill_label(self) -> str:
        """Skill name without the leading slash, used for selector matching."""
        return self.skill_name.lstrip("/")
