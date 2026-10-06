"""Shared plumbing for the autopilot agents: config, persistent state, secrets, results."""
from __future__ import annotations

import json
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CURRENCY_CODES = {"$": "usd", "£": "gbp", "€": "eur"}
THEMES = ("sage", "blush", "midnight")


@dataclass
class Result:
    status: str  # "ok" | "skipped" | "needs_setup" | "error"
    summary: str

    @staticmethod
    def ok(msg):
        return Result("ok", msg)

    @staticmethod
    def skipped(msg):
        return Result("skipped", msg)

    @staticmethod
    def needs_setup(msg):
        return Result("needs_setup", msg)


@dataclass
class Variant:
    year: int
    currency: str
    theme: str
    price: float
    gumroad_url: str = ""

    @property
    def id(self):
        return f"budget-{self.year}-{CURRENCY_CODES[self.currency]}-{self.theme}"

    @property
    def name(self):
        return f"{self.year} Budget & Finance Planner"

    def as_dict(self):
        return {"year": self.year, "currency": self.currency, "theme": self.theme, "price": self.price}


@dataclass
class Ctx:
    root: Path
    config: dict
    state: dict
    today: date
    dry_run: bool = False
    log_lines: list = field(default_factory=list)
    cache: dict = field(default_factory=dict)  # per-run scratch shared between agents (e.g. access tokens)

    def log(self, msg):
        print(msg)
        self.log_lines.append(msg)

    def env(self, name, default=""):
        return os.environ.get(name, default)

    @property
    def dist(self):
        return self.root / "dist"

    @property
    def reports(self):
        return self.root / "reports"

    def variants(self):
        """Variants from autopilot.toml plus any the strategist added (when auto_expand is on)."""
        seen, out = set(), []
        for raw in list(self.config.get("variants", [])) + list(self.state.get("extra_variants", [])):
            v = Variant(int(raw["year"]), raw["currency"], raw["theme"], float(raw["price"]),
                        raw.get("gumroad_url", ""))
            if v.currency not in CURRENCY_CODES or v.theme not in THEMES:
                self.log(f"  ! ignoring variant with unsupported currency/theme: {raw}")
                continue
            if v.id not in seen:
                seen.add(v.id)
                out.append(v)
        return out

    def vstate(self, variant_id):
        return self.state.setdefault("variants", {}).setdefault(variant_id, {})

    def store_link(self, v):
        """Best public link for a variant: live Etsy listing, else its Gumroad page, else the shop-wide Gumroad page."""
        vs = self.state.get("variants", {}).get(v.id, {})
        if vs.get("etsy_state") == "active" and vs.get("etsy_url"):
            return vs["etsy_url"]
        return v.gumroad_url or self.config.get("store", {}).get("gumroad_url", "")


def load_dotenv(root=ROOT):
    """Load KEY=VALUE lines from .env (local runs). Real environment variables win."""
    path = root / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def persist_secret(ctx, name, value):
    """Save a rotated credential (e.g. an Etsy refresh token) so the next run can use it.

    Locally it rewrites .env; on GitHub Actions it updates the repo secret when GH_PAT is set.
    Returns True when it was persisted somewhere durable.
    """
    os.environ[name] = value
    saved = False
    env_file = ctx.root / ".env"
    if env_file.exists():
        lines = env_file.read_text().splitlines()
        lines = [l for l in lines if not l.startswith(f"{name}=")] + [f"{name}={value}"]
        env_file.write_text("\n".join(lines) + "\n")
        saved = True
    repo, pat = ctx.env("GITHUB_REPOSITORY"), ctx.env("GH_PAT")
    if repo and pat and not ctx.dry_run:
        proc = subprocess.run(["gh", "secret", "set", name, "--repo", repo, "--body", value],
                              env={**os.environ, "GH_TOKEN": pat}, capture_output=True, text=True)
        if proc.returncode == 0:
            saved = True
        else:
            ctx.log(f"  ! could not update GitHub secret {name}: {proc.stderr.strip()}")
    return saved


def load_config(root=ROOT):
    with open(root / "autopilot.toml", "rb") as f:
        return tomllib.load(f)


def load_state(root=ROOT):
    path = root / "state" / "state.json"
    return json.loads(path.read_text()) if path.exists() else {}


def save_state(root, state):
    path = root / "state" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n")


def copy_path(root, variant_id):
    return root / "state" / "copy" / f"{variant_id}.json"


def load_copy(root, variant_id):
    path = copy_path(root, variant_id)
    return json.loads(path.read_text()) if path.exists() else None
